#!/usr/bin/env python3
"""定时截图与检测结果记录节点。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Float32MultiArray

try:
    from cv_bridge import CvBridge
except ImportError:
    CvBridge = None


class ScreenshotNode(Node):
    """保存截图，并在需要时把检测框叠加到图像上。"""

    def __init__(self) -> None:
        super().__init__('screenshot_node')

        self.declare_parameters(
            namespace='',
            parameters=[
                ('image_topic', '/image_raw'),
                ('detection_topic', 'vision/target_bbox'),
                ('screenshot_interval_sec', 5.0),
                ('output_dir', '/tmp/mydroid_screenshots'),
                ('enable_detection_overlay', True),
                ('save_video', False),
                ('video_fps', 30.0),
                ('log_terminal', True),
            ],
        )

        self.image_topic = str(self.get_parameter('image_topic').value)
        self.detection_topic = str(self.get_parameter('detection_topic').value)
        self.screenshot_interval = float(self.get_parameter('screenshot_interval_sec').value)
        self.output_dir = Path(self.get_parameter('output_dir').value)
        self.enable_overlay = bool(self.get_parameter('enable_detection_overlay').value)
        self.save_video = bool(self.get_parameter('save_video').value)
        self.video_fps = float(self.get_parameter('video_fps').value)
        self.log_terminal = bool(self.get_parameter('log_terminal').value)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_count = 0

        self.bridge = CvBridge() if CvBridge is not None else None
        if self.bridge is None:
            raise RuntimeError('cv_bridge is required')

        self.latest_frame: Optional[np.ndarray] = None
        self.latest_detection: Optional[dict] = None
        self.frame_lock = threading.Lock()
        self.last_screenshot_time = 0.0
        self.video_writer = None

        self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        self.detection_sub = self.create_subscription(
            Float32MultiArray,
            self.detection_topic,
            self.detection_callback,
            10,
        )
        self.timer = self.create_timer(1.0, self.timer_callback)

        self.get_logger().info(
            f'Screenshot node started. interval={self.screenshot_interval}s output={self.output_dir}'
        )

    def image_callback(self, msg: Image) -> None:
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with self.frame_lock:
                self.latest_frame = frame.copy()
        except Exception as exc:
            self.get_logger().error(f'Image conversion failed: {exc}')

    def detection_callback(self, msg: Float32MultiArray) -> None:
        try:
            # 新协议：
            # [cx_norm, cy_norm, w_norm, h_norm, conf, area_norm, distance, image_w, image_h]
            if len(msg.data) >= 9:
                self.latest_detection = {
                    'cx': float(msg.data[0]),
                    'cy': float(msg.data[1]),
                    'w': float(msg.data[2]),
                    'h': float(msg.data[3]),
                    'conf': float(msg.data[4]),
                    'distance': float(msg.data[6]),
                    'image_w': float(msg.data[7]),
                    'image_h': float(msg.data[8]),
                    'normalized': True,
                }
                return

            # 兼容旧协议：
            # [cx_px, cy_px, w_px, h_px, conf, distance]
            if len(msg.data) >= 6:
                self.latest_detection = {
                    'cx': float(msg.data[0]),
                    'cy': float(msg.data[1]),
                    'w': float(msg.data[2]),
                    'h': float(msg.data[3]),
                    'conf': float(msg.data[4]),
                    'distance': float(msg.data[5]),
                    'image_w': 0.0,
                    'image_h': 0.0,
                    'normalized': False,
                }
                return

            self.latest_detection = None
        except Exception as exc:
            self.get_logger().error(f'Detection parsing failed: {exc}')

    def _init_video_writer(self) -> None:
        if self.latest_frame is None:
            self.get_logger().warning('No frame available, video writer not initialized')
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_path = self.output_dir / f'recording_{timestamp}.mp4'
        frame_h, frame_w = self.latest_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(str(video_path), fourcc, self.video_fps, (frame_w, frame_h))
        self.get_logger().info(f'Video recording started: {video_path}')

    def _detection_to_pixels(self, detection: dict, frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
        if detection.get('normalized', False):
            source_w = float(detection.get('image_w') or frame_w)
            source_h = float(detection.get('image_h') or frame_h)
            scale_x = frame_w / max(source_w, 1.0)
            scale_y = frame_h / max(source_h, 1.0)

            cx_px = float(detection['cx']) * source_w * scale_x
            cy_px = float(detection['cy']) * source_h * scale_y
            width_px = float(detection['w']) * source_w * scale_x
            height_px = float(detection['h']) * source_h * scale_y
            return cx_px, cy_px, width_px, height_px

        return (
            float(detection['cx']),
            float(detection['cy']),
            float(detection['w']),
            float(detection['h']),
        )

    def _draw_detection(self, frame: np.ndarray, detection: dict) -> np.ndarray:
        if not detection or np.isnan(detection['cx']):
            return frame

        frame = frame.copy()
        frame_h, frame_w = frame.shape[:2]
        cx_px, cy_px, width_px, height_px = self._detection_to_pixels(detection, frame_w, frame_h)

        x1 = int(cx_px - width_px / 2.0)
        y1 = int(cy_px - height_px / 2.0)
        x2 = int(cx_px + width_px / 2.0)
        y2 = int(cy_px + height_px / 2.0)

        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(frame, (int(cx_px), int(cy_px)), 5, (0, 0, 255), -1)
        cv2.putText(
            frame,
            f"Conf: {detection['conf']:.2f} Dist: {detection['distance']:.2f}m",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.line(frame, (frame_w // 2 - 20, frame_h // 2), (frame_w // 2 + 20, frame_h // 2), (255, 0, 0), 1)
        cv2.line(frame, (frame_w // 2, frame_h // 2 - 20), (frame_w // 2, frame_h // 2 + 20), (255, 0, 0), 1)
        return frame

    def _save_screenshot(self) -> None:
        with self.frame_lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()
            detection = self.latest_detection

        if frame is None:
            self.get_logger().warning('No frame available for screenshot')
            return

        display_frame = frame.copy()
        if self.enable_overlay and detection:
            display_frame = self._draw_detection(display_frame, detection)

        filename = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3] + '.jpg'
        filepath = self.output_dir / filename
        cv2.imwrite(str(filepath), display_frame)
        self.screenshot_count += 1

        log_msg = f'[#{self.screenshot_count:04d}] Screenshot saved: {filepath.name}'
        if detection and not np.isnan(detection['cx']):
            if detection.get('normalized', False):
                log_msg += (
                    f' | Target: cx={detection["cx"]:.3f} cy={detection["cy"]:.3f} '
                    f'conf={detection["conf"]:.2f} dist={detection["distance"]:.2f}m'
                )
            else:
                log_msg += (
                    f' | Target: cx={detection["cx"]:.0f} cy={detection["cy"]:.0f} '
                    f'conf={detection["conf"]:.2f} dist={detection["distance"]:.2f}m'
                )
        else:
            log_msg += ' | [No target]'

        if self.log_terminal:
            self.get_logger().info(log_msg)
        else:
            print(log_msg)

        if self.save_video and self.video_writer is not None:
            try:
                self.video_writer.write(display_frame)
            except Exception as exc:
                self.get_logger().error(f'Failed to write video frame: {exc}')

    def timer_callback(self) -> None:
        current_time = time.time()
        if current_time - self.last_screenshot_time >= self.screenshot_interval:
            if self.save_video and self.video_writer is None and self.latest_frame is not None:
                self._init_video_writer()
            self._save_screenshot()
            self.last_screenshot_time = current_time

    def destroy_node(self) -> bool:
        if self.video_writer is not None:
            self.video_writer.release()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ScreenshotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
