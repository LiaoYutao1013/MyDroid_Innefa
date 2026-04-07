#!/usr/bin/env python3
"""YOLOv8 目标检测节点（降级版）- 不依赖 ultralytics。

改进说明：
1. 使用肤色检测替代 YOLO 推理（适用于检测人体）
2. 兼容原有的 ROS2 接口（发布 vision/target_bbox）
3. 支持 camera_test_mode 和直接摄像头模式
4. 在网络不可用时仍可工作

发布话题：
- vision/target_bbox: Float32MultiArray [cx, cy, w, h, conf, distance_m]
"""

from __future__ import annotations

from typing import Optional, Union
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


class YoloDetectionNode(Node):
    """使用肤色检测的目标检测节点（不需要 YOLO/ultralytics）。"""

    def __init__(self) -> None:
        """初始化图像输入源、参数和定时器。"""
        super().__init__('yolo_detection_node')

        # 参数定义（与原节点兼容）
        self.declare_parameters(
            namespace='',
            parameters=[
                ('camera_device', '/dev/video0'),
                ('camera_test_mode', False),
                ('image_topic', '/image_raw'),
                ('frame_width', 640),
                ('frame_height', 480),
                ('camera_fps', 30.0),
                ('inference_rate_hz', 10.0),
                ('camera_retry_sec', 2.0),
                ('model_path', 'yolov8n.pt'),  # 不使用，保留以兼容
                ('input_size', 416),  # 不使用，保留以兼容
                ('confidence_threshold', 0.45),
                ('iou_threshold', 0.45),
                ('device', 'cpu'),  # 不使用，保留以兼容
                ('target_class_names', ['person']),
                ('target_real_height_m', 1.70),
                ('camera_focal_length_px', 650.0),
                ('publish_no_target', True),
                ('log_interval_sec', 1.0),
            ],
        )

        # 读取参数
        self.camera_device = str(self.get_parameter('camera_device').value)
        self.camera_test_mode = bool(self.get_parameter('camera_test_mode').value)
        self.image_topic = str(self.get_parameter('image_topic').value)
        self.frame_width = int(self.get_parameter('frame_width').value)
        self.frame_height = int(self.get_parameter('frame_height').value)
        self.camera_fps = float(self.get_parameter('camera_fps').value)
        self.inference_rate_hz = float(self.get_parameter('inference_rate_hz').value)
        self.camera_retry_sec = float(self.get_parameter('camera_retry_sec').value)
        self.confidence_threshold = float(self.get_parameter('confidence_threshold').value)
        self.target_real_height_m = float(self.get_parameter('target_real_height_m').value)
        self.camera_focal_length_px = float(self.get_parameter('camera_focal_length_px').value)
        self.publish_no_target = bool(self.get_parameter('publish_no_target').value)
        self.log_interval_sec = float(self.get_parameter('log_interval_sec').value)

        # 发布器
        self.target_pub = self.create_publisher(Float32MultiArray, 'vision/target_bbox', 10)

        # 图像输入相关状态
        self.cap: Optional[cv2.VideoCapture] = None
        self.bridge = CvBridge() if CvBridge is not None else None
        self.latest_frame = None
        self.last_retry_time = self.get_clock().now()
        self.last_inference_time = self.get_clock().now()
        self.last_log_time = self.get_clock().now()
        self.image_sub = None
        self.prev_frame = None

        if self.camera_test_mode:
            if self.bridge is None:
                raise RuntimeError(
                    'cv_bridge is not installed. Install ros-humble-cv-bridge before camera test mode.'
                )
            self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        else:
            self._open_camera()

        timer_period = 1.0 / max(self.inference_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'YOLO detection node (fallback mode - skin detection) ready. '
            f'camera_test_mode={self.camera_test_mode} camera={self.camera_device} '
            f'image_topic={self.image_topic} conf={self.confidence_threshold}'
        )

    def _open_camera(self) -> None:
        """打开本地摄像头。"""
        if self.camera_test_mode:
            return

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        source: Union[int, str] = (
            int(self.camera_device) if self.camera_device.isdigit() else self.camera_device
        )
        self.cap = cv2.VideoCapture(source)

        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.camera_device}')
            self.cap = None
            return

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.camera_fps)
        self.get_logger().info(f'Camera opened: {self.camera_device}')

    def image_callback(self, msg: Image) -> None:
        """接收 ROS 图像话题回调。"""
        try:
            if self.bridge is None:
                return
            self.latest_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Failed to convert image: {e}')

    def detect_skin_regions(self, frame: np.ndarray) -> list[dict]:
        """使用肤色检测找人体。"""
        if frame is None or frame.size == 0:
            return []

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
            if area < 500:  # 最小面积阈值
                continue

            x, y, w, h = cv2.boundingRect(contour)
            cx, cy = x + w / 2, y + h / 2

            # 计算置信度（基于面积）
            conf = min(1.0, area / 10000.0)
            if conf < self.confidence_threshold:
                continue

            detections.append({
                'cx': cx,
                'cy': cy,
                'w': w,
                'h': h,
                'conf': conf,
                'area': area,
            })

        return detections

    def estimate_distance(self, bbox_height: float) -> float:
        """通过目标框高度估计距离（米）。"""
        if bbox_height <= 0:
            return 999.0

        distance = (self.target_real_height_m * self.camera_focal_length_px) / bbox_height
        return max(0.1, min(distance, 50.0))  # 限制在 0.1~50m

    def select_best_detection(self, detections: list[dict]) -> Optional[dict]:
        """选择面积最大的检测（最可能是主要目标）。"""
        if not detections:
            return None
        return max(detections, key=lambda d: d['area'])

    def timer_callback(self) -> None:
        """定时推理回调。"""
        # 获取当前帧
        frame = None
        if self.camera_test_mode:
            frame = self.latest_frame
        else:
            if self.cap is None or not self.cap.isOpened():
                # 尝试重新打开摄像头
                now = self.get_clock().now()
                if (now - self.last_retry_time).nanoseconds / 1e9 > self.camera_retry_sec:
                    self._open_camera()
                    self.last_retry_time = now
                return

            ret, frame = self.cap.read()
            if not ret:
                frame = None

        if frame is None or frame.size == 0:
            return

        # 检测
        detections = self.detect_skin_regions(frame)

        # 选择最优目标
        best_det = self.select_best_detection(detections)

        # 发布结果
        if best_det or self.publish_no_target:
            msg = Float32MultiArray()
            if best_det:
                distance = self.estimate_distance(best_det['h'])
                msg.data = [
                    float(best_det['cx']),
                    float(best_det['cy']),
                    float(best_det['w']),
                    float(best_det['h']),
                    float(best_det['conf']),
                    float(distance),
                ]
            else:
                # 无目标时发布 NaN
                msg.data = [float('nan')] * 6

            self.target_pub.publish(msg)

        # 日志输出
        now = self.get_clock().now()
        if (now - self.last_log_time).nanoseconds / 1e9 > self.log_interval_sec:
            if best_det:
                distance = self.estimate_distance(best_det['h'])
                self.get_logger().info(
                    f'Detection: cx={best_det["cx"]:.0f} cy={best_det["cy"]:.0f} '
                    f'w={best_det["w"]:.0f} h={best_det["h"]:.0f} '
                    f'conf={best_det["conf"]:.2f} dist={distance:.2f}m'
                )
            else:
                self.get_logger().info('No target detected')
            self.last_log_time = now


def main(args=None) -> None:
    """ROS2 节点入口。"""
    rclpy.init(args=args)
    node = YoloDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.cap is not None:
            node.cap.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
