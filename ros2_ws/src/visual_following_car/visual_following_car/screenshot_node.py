#!/usr/bin/env python3
"""摄像头定时截图与检测结果记录节点。

功能：
1. 订阅摄像头图像和检测结果
2. 定时保存截图（带检测框和信息）
3. 输出到终端和文件
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Optional
import threading

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
    """截图与检测结果记录节点。"""

    def __init__(self) -> None:
        super().__init__('screenshot_node')

        # 参数声明
        self.declare_parameters(
            namespace='',
            parameters=[
                ('image_topic', '/image_raw'),
                ('detection_topic', 'vision/target_bbox'),
                ('screenshot_interval_sec', 5.0),  # 5秒截一次
                ('output_dir', '/tmp/mydroid_screenshots'),
                ('enable_detection_overlay', True),  # 在图像上绘制检测框
                ('save_video', False),  # 是否保存视频
                ('video_fps', 30.0),
                ('log_terminal', True),  # 在终端显示检测结果
            ],
        )

        # 读取参数
        self.image_topic = str(self.get_parameter('image_topic').value)
        self.detection_topic = str(self.get_parameter('detection_topic').value)
        self.screenshot_interval = float(self.get_parameter('screenshot_interval_sec').value)
        self.output_dir = Path(self.get_parameter('output_dir').value)
        self.enable_overlay = bool(self.get_parameter('enable_detection_overlay').value)
        self.save_video = bool(self.get_parameter('save_video').value)
        self.video_fps = float(self.get_parameter('video_fps').value)
        self.log_terminal = bool(self.get_parameter('log_terminal').value)

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_count = 0

        # 图像处理
        self.bridge = CvBridge() if CvBridge is not None else None
        if self.bridge is None:
            self.get_logger().error('cv_bridge not found')
            raise RuntimeError('cv_bridge is required')

        # 状态
        self.latest_frame = None
        self.latest_detection = None
        self.frame_lock = threading.Lock()
        self.last_screenshot_time = 0

        # 订阅话题
        self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        self.detection_sub = self.create_subscription(
            Float32MultiArray, self.detection_topic, self.detection_callback, 10
        )

        # 定时器
        self.timer = self.create_timer(1.0, self.timer_callback)

        # 视频写入器
        self.video_writer = None
        if self.save_video:
            self._init_video_writer()

        self.get_logger().info(
            f'Screenshot node started. Interval: {self.screenshot_interval}s, '
            f'Output: {self.output_dir}'
        )

    def image_callback(self, msg: Image) -> None:
        """接收图像回调。"""
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            with self.frame_lock:
                self.latest_frame = frame.copy()
        except Exception as e:
            self.get_logger().error(f'Image conversion failed: {e}')

    def detection_callback(self, msg: Float32MultiArray) -> None:
        """接收检测结果回调。"""
        try:
            # 解析检测结果 [cx, cy, w, h, conf, distance]
            if len(msg.data) >= 6:
                self.latest_detection = {
                    'cx': msg.data[0],
                    'cy': msg.data[1],
                    'w': msg.data[2],
                    'h': msg.data[3],
                    'conf': msg.data[4],
                    'distance': msg.data[5],
                }
            else:
                self.latest_detection = None
        except Exception as e:
            self.get_logger().error(f'Detection parsing failed: {e}')

    def _init_video_writer(self) -> None:
        """初始化视频写入器。"""
        if not self.latest_frame is not None:
            self.get_logger().warn('No frame available, video writer not initialized')
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_path = self.output_dir / f'recording_{timestamp}.mp4'
        
        h, w = self.latest_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter(str(video_path), fourcc, self.video_fps, (w, h))
        self.get_logger().info(f'Video recording started: {video_path}')

    def _draw_detection(self, frame: np.ndarray, detection: dict) -> np.ndarray:
        """在图像上绘制检测框和信息。"""
        if not detection or np.isnan(detection['cx']):
            return frame

        frame = frame.copy()
        h, w = frame.shape[:2]

        # 检测框
        x1 = int(detection['cx'] - detection['w'] / 2)
        y1 = int(detection['cy'] - detection['h'] / 2)
        x2 = int(detection['cx'] + detection['w'] / 2)
        y2 = int(detection['cy'] + detection['h'] / 2)

        # 绘制边界框
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # 绘制中心点
        cv2.circle(frame, (int(detection['cx']), int(detection['cy'])), 5, (0, 0, 255), -1)

        # 绘制文字信息
        text = f"Conf: {detection['conf']:.2f} Dist: {detection['distance']:.2f}m"
        cv2.putText(frame, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # 绘制画面中心十字线
        cv2.line(frame, (w // 2 - 20, h // 2), (w // 2 + 20, h // 2), (255, 0, 0), 1)
        cv2.line(frame, (w // 2, h // 2 - 20), (w // 2, h // 2 + 20), (255, 0, 0), 1)

        return frame

    def _save_screenshot(self) -> None:
        """保存截图。"""
        with self.frame_lock:
            frame = self.latest_frame
            detection = self.latest_detection

        if frame is None:
            self.get_logger().warn('No frame available for screenshot')
            return

        # 准备显示帧
        display_frame = frame.copy()

        # 绘制检测结果
        if self.enable_overlay and detection:
            display_frame = self._draw_detection(display_frame, detection)

        # 保存文件
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3] + '.jpg'
        filepath = self.output_dir / filename

        cv2.imwrite(str(filepath), display_frame)
        self.screenshot_count += 1

        # 输出信息
        log_msg = f'[#{self.screenshot_count:04d}] Screenshot saved: {filepath.name}'

        if detection and not np.isnan(detection['cx']):
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

        # 写入视频
        if self.save_video and self.video_writer:
            try:
                self.video_writer.write(display_frame)
            except Exception as e:
                self.get_logger().error(f'Failed to write video frame: {e}')

    def timer_callback(self) -> None:
        """定时器回调。"""
        import time

        current_time = time.time()
        if current_time - self.last_screenshot_time >= self.screenshot_interval:
            self._save_screenshot()
            self.last_screenshot_time = current_time


def main(args=None) -> None:
    """ROS2 节点入口。"""
    rclpy.init(args=args)
    node = ScreenshotNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.video_writer:
            node.video_writer.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
