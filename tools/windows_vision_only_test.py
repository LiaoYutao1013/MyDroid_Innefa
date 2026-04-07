#!/usr/bin/env python3
"""Windows 纯视觉测试入口。

用途说明：
1. 这个脚本完全独立于现有 ROS2 节点，不导入项目里的任何 ROS 包代码。
2. 它的目标是让我们在 Windows 机器上只验证：
   - 摄像头能不能打开
   - YOLO 模型能不能检测到人
   - 目标中心点计算是否正确
   - 模拟 Pan 跟随角是否符合直觉
3. 因为它不依赖 ROS2，所以特别适合在“还没把整套环境搬到 ROCK 3B”前先快速验证视觉链路。

运行示例：
    py .\\tools\\windows_vision_only_test.py
    py .\\tools\\windows_vision_only_test.py --camera 1 --model .\\models\\yolov8n.pt
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Optional

import cv2


def clamp(value: float, minimum: float, maximum: float) -> float:
    """把输入值限制在指定范围内。"""
    return max(minimum, min(maximum, value))


def parse_args() -> argparse.Namespace:
    """解析命令行参数。

    参数设计原则：
    - 尽量与 ROS2 配置里的常见参数命名接近；
    - 这样后续我们在 Windows 和 ROS2 之间切换时，心智负担更小。
    """
    parser = argparse.ArgumentParser(
        description='Windows 纯视觉测试：摄像头 + YOLO + 模拟 Pan 跟随'
    )
    parser.add_argument('--camera', default='0', help='摄像头索引或视频文件路径，默认 0')
    parser.add_argument('--model', default='yolov8n.pt', help='YOLO 模型路径，建议先用 .pt 文件')
    parser.add_argument('--class-name', default='person', help='默认跟踪类别名称')
    parser.add_argument('--input-size', type=int, default=416, help='推理输入尺寸')
    parser.add_argument('--conf', type=float, default=0.45, help='置信度阈值')
    parser.add_argument('--iou', type=float, default=0.45, help='NMS IOU 阈值')
    parser.add_argument('--device', default='cpu', help='推理设备，例如 cpu')
    parser.add_argument('--frame-width', type=int, default=640, help='摄像头宽度')
    parser.add_argument('--frame-height', type=int, default=480, help='摄像头高度')
    parser.add_argument('--target-real-height', type=float, default=1.70, help='目标真实高度，单位米')
    parser.add_argument('--focal-length-px', type=float, default=650.0, help='用于估距的像素焦距')
    parser.add_argument('--pan-neutral', type=float, default=90.0, help='Pan 中位角')
    parser.add_argument('--pan-kp', type=float, default=0.8, help='Pan 比例增益')
    parser.add_argument('--pan-min', type=float, default=0.0, help='Pan 最小角度')
    parser.add_argument('--pan-max', type=float, default=160.0, help='Pan 最大角度')
    parser.add_argument('--show-crosshair', action='store_true', help='显示画面中心十字线')
    return parser.parse_args()


def open_capture(camera_arg: str, width: int, height: int) -> cv2.VideoCapture:
    """打开摄像头或视频文件。

    使用方式：
    - 如果参数是纯数字，例如 `0`，就按摄像头索引打开。
    - 如果参数不是纯数字，就按文件路径处理。
    """
    source = int(camera_arg) if camera_arg.isdigit() else camera_arg
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def select_best_detection(result, target_class_name: str):
    """从一帧 YOLO 结果中选出“最值得跟踪”的目标。

    当前策略：
    - 只看指定类别，例如 `person`
    - 在满足类别的检测框里，选面积最大的一个

    这么做的原因是：
    - 在没有显式跟踪器的前提下，面积最大的目标通常就是最近/最重要的目标；
    - 对视觉跟随小车而言，这是一个简单且足够实用的启发式策略。
    """
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return None

    names = result.names
    best = None
    best_area = -1.0

    for box in boxes:
        cls_id = int(box.cls.item())
        if isinstance(names, dict):
            cls_name = names.get(cls_id, str(cls_id))
        else:
            cls_name = names[cls_id] if 0 <= cls_id < len(names) else str(cls_id)

        if cls_name != target_class_name:
            continue

        x1, y1, x2, y2 = box.xyxy[0].tolist()
        width = max(x2 - x1, 0.0)
        height = max(y2 - y1, 0.0)
        area = width * height

        if area <= best_area:
            continue

        best_area = area
        best = {
            'x1': x1,
            'y1': y1,
            'x2': x2,
            'y2': y2,
            'width': width,
            'height': height,
            'confidence': float(box.conf.item()),
            'class_name': cls_name,
        }

    return best


def estimate_distance(height_px: float, target_real_height_m: float, focal_length_px: float) -> float:
    """根据目标框高度粗略估算距离。

    公式：
        distance = real_height * focal_length / bbox_height

    注意：
    - 这只是一个非常粗的单目估计；
    - 主要用于可视化和跟随逻辑演示，不适合当作高精度测距。
    """
    if height_px <= 1.0 or focal_length_px <= 0.0:
        return -1.0
    return (target_real_height_m * focal_length_px) / height_px


def compute_simulated_pan(center_x_norm: float, pan_neutral: float, pan_kp: float, pan_min: float, pan_max: float) -> float:
    """根据目标水平偏差计算模拟 Pan 角。

    控制思想：
    - 画面中心为 0.5；
    - 目标在左边时，`horizontal_error = 0.5 - center_x_norm` 为正；
    - 使用一个简单 P 控制，把误差映射到角度偏转。
    """
    horizontal_error = 0.5 - center_x_norm
    target_pan = pan_neutral + (horizontal_error * pan_kp * 180.0)
    return clamp(target_pan, pan_min, pan_max)


def draw_overlay(
    frame,
    detection,
    fps: float,
    pan_angle: Optional[float],
    distance_m: float,
    show_crosshair: bool,
) -> None:
    """在图像上叠加调试信息。"""
    frame_h, frame_w = frame.shape[:2]

    if show_crosshair:
        cv2.line(frame, (frame_w // 2, 0), (frame_w // 2, frame_h), (255, 255, 0), 1)
        cv2.line(frame, (0, frame_h // 2), (frame_w, frame_h // 2), (255, 255, 0), 1)

    if detection is not None:
        x1 = int(detection['x1'])
        y1 = int(detection['y1'])
        x2 = int(detection['x2'])
        y2 = int(detection['y2'])
        cx = int((detection['x1'] + detection['x2']) * 0.5)
        cy = int((detection['y1'] + detection['y2']) * 0.5)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 220, 0), 2)
        cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)

        label = f"{detection['class_name']} {detection['confidence']:.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2)

    info_lines = [
        f'FPS: {fps:.2f}',
        f'Pan(sim): {pan_angle:.2f} deg' if pan_angle is not None else 'Pan(sim): N/A',
        f'Distance(est): {distance_m:.2f} m' if distance_m > 0.0 else 'Distance(est): N/A',
        'Press Q to quit',
    ]

    for index, text in enumerate(info_lines):
        y = 30 + (index * 28)
        cv2.putText(frame, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (40, 180, 255), 2)


def main() -> None:
    """程序主入口。"""
    args = parse_args()

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            '未检测到 ultralytics。请先执行: py -m pip install -r .\\tools\\windows_vision_only_requirements.txt'
        ) from exc

    model_path = Path(args.model)
    print(f'[INFO] 模型路径: {model_path}')
    print(f'[INFO] 摄像头参数: {args.camera}')
    print('[INFO] 按 Q 退出。')

    model = YOLO(str(model_path))
    cap = open_capture(args.camera, args.frame_width, args.frame_height)

    if not cap.isOpened():
        raise SystemExit(f'无法打开摄像头/视频源: {args.camera}')

    last_time = time.perf_counter()

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print('[WARN] 读取画面失败，结束测试。')
                break

            results = model.predict(
                source=frame,
                verbose=False,
                imgsz=args.input_size,
                conf=args.conf,
                iou=args.iou,
                device=args.device,
            )

            result = results[0]
            best = select_best_detection(result, args.class_name)

            now = time.perf_counter()
            fps = 1.0 / max(now - last_time, 1e-6)
            last_time = now

            pan_angle = None
            distance_m = -1.0

            if best is not None:
                frame_h, frame_w = frame.shape[:2]
                center_x = ((best['x1'] + best['x2']) * 0.5) / max(frame_w, 1)
                distance_m = estimate_distance(
                    best['height'],
                    args.target_real_height,
                    args.focal_length_px,
                )
                pan_angle = compute_simulated_pan(
                    center_x,
                    args.pan_neutral,
                    args.pan_kp,
                    args.pan_min,
                    args.pan_max,
                )

                print(
                    '[TRACK] '
                    f'fps={fps:5.2f} '
                    f'center_x={center_x:.3f} '
                    f'conf={best["confidence"]:.2f} '
                    f'pan={pan_angle:.2f} '
                    f'distance={distance_m:.2f}m'
                )
            else:
                print(f'[TRACK] fps={fps:5.2f} no target')

            draw_overlay(
                frame=frame,
                detection=best,
                fps=fps,
                pan_angle=pan_angle,
                distance_m=distance_m,
                show_crosshair=args.show_crosshair,
            )

            cv2.imshow('Windows Vision Only Test', frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q')):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
