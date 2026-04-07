from rknn.api import RKNN
import sys

if len(sys.argv) <3:
    print("Usage: python convert_to_rknn.py <input.onnx> <output.rknn>")
    sys.exit(1)

ONNX_MODEL = 'RetinaFace_mobile320.onnx'
RKNN_MODEL = 'RetinaFace_mobile320.rknn'

rknn = RKNN(verbose=True)

print('--> Config model')
rknn.config(
    target_platform='rk2568',
    mean_values=[[0,0,0]],
    std_values=[[255,255,255]],
    quantized = False,
    #quantized_algorithm='normal',
    #optimization_level=3
)

print('--> Loading ONNX model')
ret = rknn.load._onnx(
    model = ONNX_MODEL,
    input_size_list = [[1,3,640,640]]
)
if ret != 0:
    print('Load ONNX failed')
    exit(ret)

print('--> Building model')
ret = rknn.build(do_quantization=False)
if ret != 0:
    print('Build failed')
    exit(ret)

print('--> Exporting model')
ret = rknn.export(RKNN_MODEL)
if ret != 0:
    print('Export failed')
    exit(ret)

print(f'转换成功！生成文件：{RKNN_MODEL}')
rknn.release()