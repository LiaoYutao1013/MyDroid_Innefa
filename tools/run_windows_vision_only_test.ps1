# Windows 纯视觉测试启动脚本
#
# 设计目标：
# 1. 这个脚本只负责在 Windows 上启动独立视觉测试，不依赖 ROS2。
# 2. 所有参数都会原样转发给 windows_vision_only_test.py。
# 3. 如果你后面需要切换摄像头号、模型路径或阈值，只要在 PowerShell 里加参数即可。
#
# 示例：
#   .\tools\run_windows_vision_only_test.ps1
#   .\tools\run_windows_vision_only_test.ps1 --camera 1
#   .\tools\run_windows_vision_only_test.ps1 --model .\ros2_ws\src\visual_following_car\models\yolov8n.pt

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$scriptPath = Join-Path $PSScriptRoot 'windows_vision_only_test.py'

Write-Host "[INFO] Repo root: $repoRoot"
Write-Host "[INFO] Python script: $scriptPath"

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py $scriptPath @args
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $scriptPath @args
    exit $LASTEXITCODE
}

throw "未找到 py 或 python。请先安装 Python 3，并确保其已加入 PATH。"
