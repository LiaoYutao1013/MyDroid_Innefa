# migration_move_to_tools_models.ps1
# 用于将脚本与模型移动到 tools/ 和 models/ 并创建 package stub
# 在本地 PowerShell 中运行：
#   .\migration_move_to_tools_models.ps1

$ErrorActionPreference = 'Stop'
Write-Host "[INFO] Starting migration script..."

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "git not found in PATH. Install Git and retry."
    exit 1
}

try {
    git rev-parse --is-inside-work-tree > $null 2>&1
} catch {
    Write-Error "Not inside a git repository. Run this script from the repository root."
    exit 1
}

$branch = 'chore/refactor/dirs'
# checkout or create branch
$exists = git rev-parse --verify $branch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[INFO] Branch '$branch' exists. Checking out..."
    git checkout $branch
} else {
    Write-Host "[INFO] Creating branch '$branch'..."
    git checkout -b $branch
}

# create target directories
Write-Host "[INFO] Creating target directories..."
New-Item -ItemType Directory -Force -Path .\tools, .\models, .\src\mydroid_utils, .\tests | Out-Null

# files to move (source -> destination)
$moves = @(
    @{ src='convert_to_rknn.py'; dst='tools\convert_to_rknn.py' },
    @{ src='convert_ONNX_to_RKNN.py'; dst='tools\convert_ONNX_to_RKNN.py' },
    @{ src='check_model_io.py'; dst='tools\check_model_io.py' },
    @{ src='test_vision_offline.py'; dst='tools\test_vision_offline.py' },
    @{ src='test_vision_fallback.py'; dst='tools\test_vision_fallback.py' },
    @{ src='test_vision_pytorch.py'; dst='tools\test_vision_pytorch.py' },
    @{ src='yolov8n.onnx'; dst='models\yolov8n.onnx' },
    @{ src='yolov8n.pt'; dst='models\yolov8n.pt' },
    @{ src='RetinaFace_mobile320.onnx'; dst='models\RetinaFace_mobile320.onnx' },
    @{ src='RetinaFace_mobile320.rknn'; dst='models\RetinaFace_mobile320.rknn' }
)

foreach ($m in $moves) {
    $s = $m.src
    $d = $m.dst
    if (Test-Path $s) {
        Write-Host "[mv] $s -> $d"
        git mv --force $s $d
    } else {
        Write-Host "[skip] $s not found"
    }
}

# create minimal package init
$initPath = '.\src\mydroid_utils\__init__.py'
if (-not (Test-Path $initPath)) {
    Write-Host "[INFO] Creating $initPath"
    Set-Content -Path $initPath -Value "# mydroid utils package`n`n__all__ = []" -Force
} else {
    Write-Host "[INFO] $initPath already exists"
}

# stage and commit
Write-Host "[INFO] Staging changes..."
git add -A

# check if there is anything to commit
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "[INFO] No changes to commit."
} else {
    $msg1 = 'chore: reorganize repository layout (tools/, models/, src/)'
    $msg2 = "Move utility scripts into tools/ and place ML models into models.`n`nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    Write-Host "[INFO] Committing changes..."
    git commit -m $msg1 -m $msg2
}

# push branch
Write-Host "[INFO] Pushing branch to origin..."
git push -u origin HEAD

Write-Host "[DONE] Migration script finished. Review the branch and run tests."
