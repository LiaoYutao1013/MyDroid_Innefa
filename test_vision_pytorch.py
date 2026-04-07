#!/usr/bin/env python3
"""离线环境下的纯视觉测试 - 使用 PyTorch 模型推理。

无需 ultralytics，直接使用 PyTorch 推理 .pt 模型。
"""

import cv2
import numpy as np
import torch
import argparse
from pathlib import Path


def clamp(value: float, minimum: float, maximum: float) -> float:
    """把输入值限制在指定范围内。"""
    return max(minimum, min(maximum, value))


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description='纯视觉测试：摄像头 + YOLO(PyTorch) + 模拟 Pan 跟随'
    )
    parser.add_argument('--camera', default='0', help='摄像头索引或视频文件路径')
    parser.add_argument('--model', default='yolov8n.pt', help='YOLO PyTorch 模型路径')
    parser.add_argument('--input-size', type=int, default=640, help='推理输入尺寸')
    parser.add_argument('--conf', type=float, default=0.45, help='置信度阈值')
    parser.add_argument('--iou', type=float, default=0.45, help='NMS IOU 阈值')
    parser.add_argument('--frame-width', type=int, default=640, help='摄像头宽度')
    parser.add_argument('--frame-height', type=int, default=480, help='摄像头高度')
    parser.add_argument('--pan-neutral', type=float, default=90.0, help='Pan 中位角')
    parser.add_argument('--pan-kp', type=float, default=0.8, help='Pan 比例增益')
    parser.add_argument('--pan-min', type=float, default=0.0, help='Pan 最小角度')
    parser.add_argument('--pan-max', type=float, default=160.0, help='Pan 最大角度')
    parser.add_argument('--show-info', action='store_true', help='显示详细信息')
    parser.add_argument('--device', default='cpu', help='推理设备：cpu 或 cuda')
    return parser.parse_args()


def open_capture(camera_arg: str, width: int, height: int) -> cv2.VideoCapture:
    """打开摄像头或视频文件。"""
    source = int(camera_arg) if camera_arg.isdigit() else camera_arg
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def preprocess_frame(frame: np.ndarray, input_size: int) -> tuple[np.ndarray, tuple[int, int], tuple[float, float]]:
    """预处理帧，返回 (B, C, H, W) 的 tensor 和缩放信息。"""
    h, w = frame.shape[:2]
    
    # 按比例缩放
    scale = input_size / max(h, w)
    new_h, new_w = int(h * scale), int(w * scale)
    
    # 创建输入画布
    image = np.ones((input_size, input_size, 3), dtype=np.uint8) * 114
    
    # 缩放帧
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    
    # 放置到中心
    y_offset = (input_size - new_h) // 2
    x_offset = (input_size - new_w) // 2
    image[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
    
    # 转为 RGB（OpenCV 默认是 BGR）
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # 转为 tensor：(C, H, W) -> (1, C, H, W)
    image = image.astype(np.float32) / 255.0
    tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)  # (1, 3, H, W)
    
    return tensor, (x_offset, y_offset), (scale, scale)


def select_best_detection(detections: list[dict], target_class: int = 0) -> dict | None:
    """选择最优的检测目标。"""
    if not detections:
        return None
    
    # 筛选目标类别
    target_dets = [d for d in detections if d['class_id'] == target_class and d['conf'] > 0.3]
    if not target_dets:
        return None
    
    # 按面积排序
    best = max(target_dets, key=lambda d: d['w'] * d['h'])
    return best


def calculate_pan_angle(det: dict | None, frame_w: int, 
                       pan_neutral: float, pan_kp: float,
                       pan_min: float, pan_max: float) -> float:
    """根据检测目标计算 Pan 角度。"""
    if det is None:
        return pan_neutral
    
    # 目标中心相对于画面中心的偏移
    target_center_x = det['x']
    frame_center_x = frame_w / 2.0
    error_px = target_center_x - frame_center_x
    
    # 比例控制
    angle_offset = error_px * pan_kp / frame_center_x * 30
    pan_angle = clamp(pan_neutral + angle_offset, pan_min, pan_max)
    
    return pan_angle


def main():
    args = parse_args()
    
    # 检查模型
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[ERROR] 模型不存在: {model_path}")
        return
    
    # 检查 PyTorch 是否可用
    try:
        import torch
        print(f"[INFO] PyTorch 版本: {torch.__version__}")
        device = torch.device(args.device if torch.cuda.is_available() else 'cpu')
        print(f"[INFO] 推理设备: {device}")
    except ImportError:
        print("[ERROR] 未找到 PyTorch，请安装: pip install torch torchvision")
        return
    
    # 尝试加载模型
    print(f"[INFO] 加载模型: {model_path}")
    try:
        model = torch.jit.load(str(model_path)) if str(model_path).endswith('.pt') else torch.load(model_path)
        model = model.to(device)
        model.eval()
        print("[INFO] 模型加载成功")
    except Exception as e:
        print(f"[ERROR] 模型加载失败: {e}")
        print("[INFO] 尝试降级推理（仅用于测试）...")
        model = None
    
    # 打开摄像头
    cap = open_capture(args.camera, args.frame_width, args.frame_height)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开摄像头: {args.camera}")
        return
    
    print("[INFO] 摄像头已打开，开始推理... (按 Ctrl+C 停止)")
    frame_count = 0
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[INFO] 视频已结束")
                break
            
            frame_h, frame_w = frame.shape[:2]
            frame_count += 1
            
            # 预处理
            tensor, (offset_x, offset_y), (scale_x, scale_y) = preprocess_frame(frame, args.input_size)
            
            detections = []
            pan_angle = args.pan_neutral
            
            # 推理（如果模型加载成功）
            if model is not None:
                try:
                    with torch.no_grad():
                        tensor = tensor.to(device)
                        outputs = model(tensor) if hasattr(model, '__call__') else model.forward(tensor)
                    
                    # YOLOv8 输出处理
                    if isinstance(outputs, torch.Tensor):
                        # outputs shape: (1, 84, num_detections) 或 (1, num_detections, 84)
                        if outputs.shape[1] == 84:
                            outputs = outputs.permute(0, 2, 1)  # 转为 (1, num_detections, 84)
                        
                        predictions = outputs[0].cpu().numpy()  # (num_detections, 84)
                        
                        for pred in predictions:
                            x, y, w, h = pred[:4]
                            conf = pred[4]
                            
                            if conf < args.conf:
                                continue
                            
                            # 类别处理
                            class_confs = pred[5:85]  # YOLOv8: 80 classes
                            class_id = int(np.argmax(class_confs))
                            class_conf = float(class_confs[class_id])
                            
                            # 反缩放
                            x = (x - offset_x) / scale_x
                            y = (y - offset_y) / scale_y
                            w = w / scale_x
                            h = h / scale_y
                            
                            detections.append({
                                'x': x,
                                'y': y,
                                'w': w,
                                'h': h,
                                'x1': max(0, x - w/2),
                                'y1': max(0, y - h/2),
                                'x2': min(frame_w, x + w/2),
                                'y2': min(frame_h, y + h/2),
                                'conf': conf,
                                'class_id': class_id,
                                'class_conf': class_conf,
                            })
                
                except Exception as e:
                    print(f"[WARN] Frame {frame_count} 推理失败: {e}")
            
            # 选择最优目标
            best_det = select_best_detection(detections, target_class=0)
            
            # 计算 Pan 角度
            pan_angle = calculate_pan_angle(
                best_det, frame_w,
                args.pan_neutral, args.pan_kp,
                args.pan_min, args.pan_max
            )
            
            # 输出到终端
            if frame_count % 10 == 0:
                status = "✓" if best_det else "✗"
                print(f"[Frame {frame_count:5d}] {status} Det: {len(detections):2d} | Pan: {pan_angle:6.1f}°", 
                      end='\r')
    
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    
    finally:
        cap.release()
        print(f"\n[INFO] 处理了 {frame_count} 帧，程序已退出")


if __name__ == '__main__':
    main()
