#!/usr/bin/env python3
"""纯视觉测试 - 降级版本（无外部 AI 框架依赖）。

当 PyTorch/TensorFlow 不可用时，使用颜色检测和边缘检测作为目标跟踪。
这允许用户测试视觉跟随控制逻辑，不受 AI 框架限制。
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
        description='纯视觉测试（降级版）：使用颜色检测的目标跟踪'
    )
    parser.add_argument('--camera', default='0', help='摄像头索引或视频文件')
    parser.add_argument('--frame-width', type=int, default=640, help='摄像头宽度')
    parser.add_argument('--frame-height', type=int, default=480, help='摄像头高度')
    parser.add_argument('--pan-neutral', type=float, default=90.0, help='Pan 中位角')
    parser.add_argument('--pan-kp', type=float, default=0.8, help='Pan 比例增益')
    parser.add_argument('--pan-min', type=float, default=0.0, help='Pan 最小角度')
    parser.add_argument('--pan-max', type=float, default=160.0, help='Pan 最大角度')
    parser.add_argument('--skin-detect', action='store_true', help='使用肤色检测（人脸）')
    parser.add_argument('--output-video', type=str, default='', help='保存输出视频路径（可选）')
    return parser.parse_args()


def open_capture(camera_arg: str, width: int, height: int) -> cv2.VideoCapture:
    """打开摄像头或视频文件。"""
    source = int(camera_arg) if camera_arg.isdigit() else camera_arg
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def detect_skin_regions(frame: np.ndarray, min_area: int = 100) -> list[dict]:
    """检测肤色区域（用于人脸/身体检测）。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # 肤色范围（HSV）
    lower_skin = np.array([0, 20, 70], dtype=np.uint8)
    upper_skin = np.array([20, 255, 255], dtype=np.uint8)
    
    mask = cv2.inRange(hsv, lower_skin, upper_skin)
    
    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    # 查找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        conf = min(1.0, area / 10000.0)  # 面积越大，置信度越高
        
        detections.append({
            'x': x + w / 2,
            'y': y + h / 2,
            'w': w,
            'h': h,
            'x1': x,
            'y1': y,
            'x2': x + w,
            'y2': y + h,
            'conf': conf,
            'area': area,
        })
    
    return detections


def detect_motion(frame: np.ndarray, prev_frame: np.ndarray | None, 
                  threshold: int = 30, min_area: int = 500) -> list[dict]:
    """基于帧差的运动检测。"""
    if prev_frame is None:
        return []
    
    # 计算帧差
    diff = cv2.absdiff(frame, prev_frame)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    
    # 二值化
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    
    # 形态学处理
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # 查找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    detections = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        conf = min(1.0, area / 10000.0)
        
        detections.append({
            'x': x + w / 2,
            'y': y + h / 2,
            'w': w,
            'h': h,
            'x1': x,
            'y1': y,
            'x2': x + w,
            'y2': y + h,
            'conf': conf,
            'area': area,
        })
    
    return detections


def select_best_detection(detections: list[dict]) -> dict | None:
    """选择面积最大的检测目标。"""
    if not detections:
        return None
    return max(detections, key=lambda d: d['area'])


def calculate_pan_angle(det: dict | None, frame_w: int,
                       pan_neutral: float, pan_kp: float,
                       pan_min: float, pan_max: float) -> float:
    """根据检测目标计算 Pan 角度。"""
    if det is None:
        return pan_neutral
    
    target_center_x = det['x']
    frame_center_x = frame_w / 2.0
    error_px = target_center_x - frame_center_x
    
    angle_offset = error_px * pan_kp / frame_center_x * 30
    pan_angle = clamp(pan_neutral + angle_offset, pan_min, pan_max)
    
    return pan_angle


def main():
    args = parse_args()
    
    # 打开摄像头
    cap = open_capture(args.camera, args.frame_width, args.frame_height)
    if not cap.isOpened():
        print(f"[ERROR] 无法打开摄像头: {args.camera}")
        return
    
    frame_h, frame_w = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    
    # 初始化视频保存器
    out = None
    if args.output_video:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(args.output_video, fourcc, 30.0, (frame_w, frame_h))
    
    print("[INFO] 摄像头已打开")
    print(f"[INFO] 分辨率: {frame_w}x{frame_h}")
    if args.skin_detect:
        print("[INFO] 使用肤色检测（人脸/身体）")
    else:
        print("[INFO] 使用运动检测")
    print("[INFO] 开始推理... (按 Ctrl+C 停止)")
    
    frame_count = 0
    prev_frame = None
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[INFO] 视频已结束")
                break
            
            frame_count += 1
            
            # 检测
            if args.skin_detect:
                detections = detect_skin_regions(frame, min_area=500)
            else:
                detections = detect_motion(frame, prev_frame, threshold=30, min_area=500)
            
            prev_frame = frame.copy()
            
            # 选择最优目标
            best_det = select_best_detection(detections)
            
            # 计算 Pan 角度
            pan_angle = calculate_pan_angle(
                best_det, frame_w,
                args.pan_neutral, args.pan_kp,
                args.pan_min, args.pan_max
            )
            
            # 绘制结果
            display = frame.copy()
            
            # 绘制中心十字
            cv2.line(display, (frame_w // 2 - 20, frame_h // 2),
                    (frame_w // 2 + 20, frame_h // 2), (0, 255, 0), 2)
            cv2.line(display, (frame_w // 2, frame_h // 2 - 20),
                    (frame_w // 2, frame_h // 2 + 20), (0, 255, 0), 2)
            
            # 绘制检测框
            for det in detections:
                x1, y1, x2, y2 = int(det['x1']), int(det['y1']), int(det['x2']), int(det['y2'])
                color = (0, 255, 0) if det == best_det else (100, 100, 100)
                cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)
                cv2.putText(display, f"{det['conf']:.2f}", (x1, y1 - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # 绘制最优目标中心
            if best_det:
                x, y = int(best_det['x']), int(best_det['y'])
                cv2.circle(display, (x, y), 5, (0, 0, 255), -1)
            
            # 显示信息
            info_text = f"Pan: {pan_angle:.1f}° | Det: {len(detections)}"
            cv2.putText(display, info_text, (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # 写入输出视频
            if out is not None:
                out.write(display)
            
            # 终端输出
            if frame_count % 10 == 0:
                status = "✓" if best_det else "✗"
                print(f"[Frame {frame_count:5d}] {status} Det: {len(detections):2d} | Pan: {pan_angle:6.1f}°",
                      end='\r')
    
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    
    finally:
        cap.release()
        if out is not None:
            out.release()
            print(f"\n[INFO] 视频已保存: {args.output_video}")
        print(f"[INFO] 处理了 {frame_count} 帧，程序已退出")


if __name__ == '__main__':
    main()
