#!/usr/bin/env python3
"""检查 YOLO ONNX 模型的输入输出格式。"""

import cv2
import numpy as np
from pathlib import Path

model_path = 'yolov8n.onnx'

if not Path(model_path).exists():
    print(f"[ERROR] 模型文件不存在: {model_path}")
    exit(1)

print(f"[INFO] 加载模型: {model_path}")
net = cv2.dnn.readNetFromONNX(model_path)

print("\n=== 模型信息 ===")
output_layer_ids = net.getUnconnectedOutLayers()
print(f"输出层数量: {len(output_layer_ids)}")

# 获取输出层名称
output_names = net.getUnconnectedOutLayersNames()
print(f"输出层名称: {output_names}")

# 创建虚拟输入测试
print("\n=== 测试推理 ===")
input_size = 640
test_blob = np.ones((1, 3, input_size, input_size), dtype=np.float32) / 255.0
print(f"输入形状: {test_blob.shape}")

net.setInput(test_blob)

# 尝试获取输出
print("\n获取每个输出层的输出:")
output_names = net.getUnconnectedOutLayersNames()
for i, layer_name in enumerate(output_names):
    try:
        output = net.forward(layer_name)
        print(f"  输出 {i} ({layer_name}): shape={output.shape}, dtype={output.dtype}")
        if output.size < 50:
            print(f"    值: {output}")
        else:
            print(f"    前5个值: {output.flat[:5]}")
    except Exception as e:
        print(f"  输出 {i} ({layer_name}) 错误: {e}")

# 尝试全层推理
print("\n全层推理输出:")
try:
    outputs = net.forward(net.getUnconnectedOutLayersNames())
    if isinstance(outputs, list):
        for i, output in enumerate(outputs):
            print(f"  输出 {i}: shape={output.shape}, dtype={output.dtype}")
            if output.size < 50:
                print(f"    值: {output}")
    else:
        print(f"  输出: shape={outputs.shape}, dtype={outputs.dtype}")
except Exception as e:
    print(f"  全层推理错误: {e}")
