from rknn.api import RKNN
import sys
import os
from pathlib import Path

# 版本检查和兼容性处理
try:
    import onnx
    onnx_version = onnx.__version__
    print(f"[INFO] ONNX 版本: {onnx_version}")
    
    # 检查 ONNX 版本兼容性
    try:
        parts = onnx_version.split('.')
        major = int(parts[0])
        minor = int(parts[1])
        
        if major < 1 or (major == 1 and minor < 13):
            print("[警告] ONNX 版本过旧，建议升级到 1.13.x 以上")
        elif major > 1 or (major == 1 and minor > 16):
            print("[警告] ONNX 版本较新，可能存在兼容性问题")
            print("[建议] 尝试降级到 ONNX 1.13-1.16 之间:")
            print("       pip install 'onnx>=1.13.0,<=1.16.0'")
    except:
        pass
        
except ImportError:
    print("[警告] 未检测到 ONNX 库，请先安装！")
except Exception as e:
    print(f"[警告] ONNX 版本检查失败: {e}")

try:
    import rknn
    rknn_version = getattr(rknn, '__version__', 'unknown')
    print(f"[INFO] RKNN 工具包已加载 (版本: {rknn_version})")
except ImportError as e:
    print(f"[错误] RKNN 工具包未安装: {e}")
    print("[提示] WSL 中请运行: pip install -r requirements_rknn.txt")
    sys.exit(1)

def main():
    # 处理命令行参数
    if len(sys.argv) >= 3:
        onnx_model = sys.argv[1]
        rknn_model = sys.argv[2]
    else:
        # 默认模型配置
        onnx_model = 'RetinaFace_mobile320.onnx'
        rknn_model = 'RetinaFace_mobile320.rknn'
        
        if len(sys.argv) == 2:
            # 如果只提供了一个参数，用作输入文件
            onnx_model = sys.argv[1]
            rknn_model = Path(onnx_model).stem + '.rknn'
    
    # 转换为 Path 对象以支持跨平台路径处理
    onnx_path = Path(onnx_model).resolve()
    rknn_path = Path(rknn_model)
    
    # 确保输出路径是绝对路径或相对于脚本目录
    if not rknn_path.is_absolute():
        script_dir = Path(__file__).parent
        rknn_path = script_dir / rknn_path
    
    print(f"输入模型：{onnx_path}")
    print(f"输出模型：{rknn_path}")
    
    # 检查输入文件是否存在
    if not onnx_path.exists():
        print(f'错误：ONNX模型文件不存在: {onnx_path}')
        sys.exit(1)
    
    try:
        rknn = RKNN(verbose=True)
        
        print('--> 配置模型 (RKNN Toolkit 2)')
        rknn.config(
            target_platform='rk3568',
            mean_values=[[0, 0, 0]],
            std_values=[[255, 255, 255]],
            optimization_level=3,
            # === RKNN 2 量化选项 ===
            # 如需启用量化，取消下行注释并选择以下之一：
            # quantized_dtype='w8a8',      # 权重8位，激活8位 - 最快，推荐
            # quantized_dtype='w8a16',     # 权重8位，激活16位 - 平衡
            # quantized_dtype='w16a16i',   # 权重16位，激活16位 - 高精度
            # quantized_dtype='w16a16i_dfp',  # 深度优化模式
            # quantized_dtype='w4a16',     # 权重4位，激活16位 - 超轻量
            # quantized_algorithm='normal',  # 或 'mmse', 'equant' 等
        )
        
        print('--> 加载 ONNX 模型')
        ret = rknn.load_onnx(
            model=str(onnx_path),
            input_size_list=[[1, 3, 640, 640]]
        )
        if ret != 0:
            print('加载 ONNX 失败')
            sys.exit(ret)
        
        print('--> 构建模型')
        ret = rknn.build(do_quantization=False)
        if ret != 0:
            print('构建失败')
            sys.exit(ret)
        
        print('--> 导出模型')
        ret = rknn.export_rknn(str(rknn_path))
        if ret != 0:
            print('导出失败')
            sys.exit(ret)
        
        print(f'✓ 转换成功！生成文件：{rknn_path}')
        rknn.release()
        return 0
        
    except Exception as e:
        print(f'错误: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    sys.exit(main())