#!/usr/bin/env python3
"""离线环境下的纯视觉测试脚本 - 使用 OpenCV DNN 推理 YOLO。

无需 ultralytics，直接使用 OpenCV 的 DNN 模块推理 ONNX 格式的 YOLO 模型。
适用于网络不可用的环境。
"""

import cv2
import numpy as np
import argparse
from pathlib import Path


def clamp(value: float, minimum: float, maximum: float) -> float:
    """把输入值限制在指定范围内。"""
    return max(minimum, min(maximum, value))


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description='离线环境纯视觉测试：摄像头 + YOLO(OpenCV DNN) + 模拟 Pan 跟随'
    )
    parser.add_argument('--camera', default='0', help='摄像头索引或视频文件路径，默认 0')
    parser.add_argument('--model', default='yolov8n.onnx', help='YOLO ONNX 模型路径')
    parser.add_argument('--input-size', type=int, default=640, help='推理输入尺寸')
    parser.add_argument('--conf', type=float, default=0.45, help='置信度阈值')
    parser.add_argument('--iou', type=float, default=0.45, help='NMS IOU 阈值')
    parser.add_argument('--frame-width', type=int, default=640, help='摄像头宽度')
    parser.add_argument('--frame-height', type=int, default=480, help='摄像头高度')
    parser.add_argument('--target-class', default='person', help='目标类别（YOLOv8 中 person 类别 ID=0）')
    parser.add_argument('--pan-neutral', type=float, default=90.0, help='Pan 中位角')
    parser.add_argument('--pan-kp', type=float, default=0.8, help='Pan 比例增益')
    parser.add_argument('--pan-min', type=float, default=0.0, help='Pan 最小角度')
    parser.add_argument('--pan-max', type=float, default=160.0, help='Pan 最大角度')
    parser.add_argument('--show-info', action='store_true', help='显示详细信息')
    return parser.parse_args()


def open_capture(camera_arg: str, width: int, height: int) -> cv2.VideoCapture:
    """打开摄像头或视频文件。"""
    source = int(camera_arg) if camera_arg.isdigit() else camera_arg
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def preprocess_frame(frame: np.ndarray, input_size: int) -> tuple[np.ndarray, tuple[float, float]]:
    """预处理帧：缩放、归一化，返回 (1, 3, H, W) 格式的 blob。"""
    h, w = frame.shape[:2]
    
    # 按比例缩放到 input_size，保持宽高比
    scale = input_size / max(h, w)
    new_h, new_w = int(h * scale), int(w * scale)
    
    # 创建 input_size x input_size 的输入，用灰色填充
    image = np.ones((input_size, input_size, 3), dtype=np.uint8) * 114
    
    # 缩放帧
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    
    # 放置到中心
    y_offset = (input_size - new_h) // 2
    x_offset = (input_size - new_w) // 2
    image[y_offset:y_offset+new_h, x_offset:x_offset+new_w] = resized
    
    # 转换为 RGB（如果输入是 BGR）
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    # 转为 float32 并归一化到 [0, 1]
    image = image.astype(np.float32) / 255.0
    
    # 转置为 (C, H, W) 然后加 batch 维度 -> (1, C, H, W)
    blob = np.transpose(image, (2, 0, 1))
    blob = np.expand_dims(blob, axis=0)
    
    return blob, (x_offset, y_offset)


def postprocess_output(output: np.ndarray, frame_h: int, frame_w: int, 
                       conf_threshold: float, input_size: int, 
                       offset_x: int, offset_y: int) -> list[dict]:
    """后处理 YOLO 输出。
    
    YOLOv8 输出格式：
    - output shape: (1, 84, 8400) 或 (batch, 84, num_predictions)
    - 每个预测：[x, y, w, h, conf, class_0, class_1, ..., class_79]
    """
    detections = []
    
    # YOLOv8 输出通常是 (batch_size, 84, 8400)
    # 转置为 (batch_size, 8400, 84)
    if output.shape[1] == 84 and output.shape[2] == 8400:
        output = output.transpose(0, 2, 1)[0]  # 取第一个batch
    else:
        output = output[0]  # 假设是 (84, 8400) 的形式
        output = output.transpose(1, 0)  # 转为 (8400, 84)
    
    # 缩放因子
    scale = input_size / max(frame_h, frame_w)
    
    for pred in output:
        x, y, w, h = pred[:4]
        conf = pred[4]  # 目标置信度
        
        if conf < conf_threshold:
            continue
        
        # 类别置信度（YOLOv8: 80 个类别）
        class_confs = pred[5:]
        class_id = np.argmax(class_confs)
        class_conf = class_confs[class_id]
        
        # 反缩放回原始图像坐标
        x = (x - offset_x) / scale
        y = (y - offset_y) / scale
        w = w / scale
        h = h / scale
        
        # 计算边界框坐标
        x1 = max(0, x - w / 2)
        y1 = max(0, y - h / 2)
        x2 = min(frame_w, x + w / 2)
        y2 = min(frame_h, y + h / 2)
        
        detections.append({
            'x': x,
            'y': y,
            'w': w,
            'h': h,
            'x1': x1,
            'y1': y1,
            'x2': x2,
            'y2': y2,
            'conf': float(conf),
            'class_id': int(class_id),
            'class_conf': float(class_conf),
        })
    
    return detections


def select_best_detection(detections: list[dict], target_class_id: int = 0) -> dict | None:
    """选择最优的检测目标（针对"person"类别）。
    
    策略：在满足类别的检测中，选面积最大的。
    """
    if not detections:
        return None
    
    # 筛选目标类别
    target_dets = [d for d in detections if d['class_id'] == target_class_id]
    if not target_dets:
        return None
    
    # 按面积排序，选最大的
    best = max(target_dets, key=lambda d: d['w'] * d['h'])
    return best


def calculate_pan_angle(det: dict | None, frame_w: int, 
                       pan_neutral: float, pan_kp: float,
                       pan_min: float, pan_max: float) -> float:
    """根据检测目标的水平位置计算 Pan 角度。"""
    if det is None:
        return pan_neutral
    
    # 目标中心相对于画面中心的偏移（像素）
    target_center_x = det['x']
    frame_center_x = frame_w / 2.0
    error_px = target_center_x - frame_center_x
    
    # 比例控制：error_px 为正表示目标在右侧
    # pan_angle 应该增大以向右转，所以增益应该是正的
    angle_offset = error_px * pan_kp / frame_center_x * 30  # 缩放因子调整
    pan_angle = clamp(pan_neutral + angle_offset, pan_min, pan_max)
    
    return pan_angle


def main():
    args = parse_args()
    
    # 打开摄像头
    cap = open_capture(args.camera, args.frame_width, args.frame_height)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开摄像头/视频: {args.camera}")
        return
    
    # 加载 YOLO 模型
    model_path = args.model
    if not Path(model_path).exists():
        print(f"[ERROR] 模型文件不存在: {model_path}")
        return
    
    print(f"[INFO] 加载模型: {model_path}")
    try:
        net = cv2.dnn.readNetFromONNX(model_path)
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    except Exception as e:
        print(f"[ERROR] 加载模型失败: {e}")
        return
    
    print("[INFO] 模型加载成功")
    print("[INFO] 开始推理... (按 Ctrl+C 停止)")
    
    frame_count = 0
    output_video_path = None
    out = None
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[INFO] 视频已结束或摄像头断开")
                break
            
            frame_h, frame_w = frame.shape[:2]
            frame_count += 1
            
            # 预处理
            blob, (offset_x, offset_y) = preprocess_frame(frame, args.input_size)
            
            # 推理
            net.setInput(blob)
            output = net.forward()
            
            # 后处理
            detections = postprocess_output(
                output, frame_h, frame_w,
                args.conf, args.input_size,
                offset_x, offset_y
            )
            
            # 选择最优目标
            best_det = select_best_detection(detections, target_class_id=0)  # person = 0
            
            # 计算 Pan 角度
            pan_angle = calculate_pan_angle(
                best_det, frame_w,
                args.pan_neutral, args.pan_kp,
                args.pan_min, args.pan_max
            )
            
            # 绘制结果
            display_frame = frame.copy()
            
            # 绘制画面中心十字
            cv2.line(display_frame, (frame_w // 2 - 20, frame_h // 2), 
                    (frame_w // 2 + 20, frame_h // 2), (0, 255, 0), 2)
            cv2.line(display_frame, (frame_w // 2, frame_h // 2 - 20),
                    (frame_w // 2, frame_h // 2 + 20), (0, 255, 0), 2)
            
            # 绘制检测框
            for det in detections:
                x1, y1, x2, y2 = int(det['x1']), int(det['y1']), int(det['x2']), int(det['y2'])
                conf = det['conf']
                color = (0, 255, 0) if det == best_det else (100, 100, 100)
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display_frame, f"{conf:.2f}", (x1, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # 绘制最优目标信息
            if best_det:
                x, y = int(best_det['x']), int(best_det['y'])
                cv2.circle(display_frame, (x, y), 5, (0, 0, 255), -1)
            
            # 显示信息
            info_text = f"Pan: {pan_angle:.1f}° | Det: {len(detections)} | Best: {best_det is not None}"
            cv2.putText(display_frame, info_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            if args.show_info and best_det:
                det_info = f"x={best_det['x']:.0f} y={best_det['y']:.0f} conf={best_det['conf']:.2f}"
                cv2.putText(display_frame, det_info, (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # 初始化视频保存器（第一帧）
            if output_video_path is None and isinstance(args.camera, str) or not args.camera.isdigit():
                output_video_path = 'vision_test_output.mp4'
                out = cv2.VideoWriter(output_video_path, fourcc, 30.0, 
                                     (display_frame.shape[1], display_frame.shape[0]))
            
            # 写入输出视频
            if out is not None:
                out.write(display_frame)
            
            # 输出到终端
            if frame_count % 10 == 0:  # 每 10 帧输出一次，避免刷屏
                status = "✓" if best_det else "✗"
                print(f"[Frame {frame_count:4d}] {status} Det: {len(detections):2d} | Pan: {pan_angle:6.1f}°", 
                      end='\r')
    
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    
    finally:
        cap.release()
        if out is not None:
            out.release()
        print(f"\n[INFO] 处理了 {frame_count} 帧，程序已退出")


if __name__ == '__main__':
    main()
