#!/usr/bin/env python3
"""RetinaFace RKNN + 肤色检测混合目标检测节点。

自动选择检测方式：
1. 优先尝试 RKNN RetinaFace（如果可用）- 更精准
2. 降级到肤色检测（如果 RKNN 不可用）- 无需额外依赖
"""

from __future__ import annotations

from typing import Optional, Union
import numpy as np
import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Float32MultiArray

try:
    from cv_bridge import CvBridge
except ImportError:
    CvBridge = None

try:
    from rknn.api import RKNN
    RKNN_AVAILABLE = True
except ImportError:
    RKNN_AVAILABLE = False


class YoloDetectionNode(Node):
    """混合检测节点：RKNN RetinaFace + 肤色检测降级。"""

    def __init__(self) -> None:
        super().__init__('yolo_detection_node')

        # 参数声明
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
                ('model_path', 'RetinaFace_mobile320.rknn'),
                ('input_size', 320),
                ('confidence_threshold', 0.5),
                ('iou_threshold', 0.4),
                ('device', 'rknn'),
                ('target_class_names', ['face']),
                ('target_real_height_m', 0.2),
                ('camera_focal_length_px', 600.0),
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
        self.model_path = str(self.get_parameter('model_path').value)
        self.input_size = int(self.get_parameter('input_size').value)
        self.confidence_threshold = float(self.get_parameter('confidence_threshold').value)
        self.target_real_height_m = float(self.get_parameter('target_real_height_m').value)
        self.camera_focal_length_px = float(self.get_parameter('camera_focal_length_px').value)
        self.publish_no_target = bool(self.get_parameter('publish_no_target').value)
        self.log_interval_sec = float(self.get_parameter('log_interval_sec').value)

        # 发布器
        self.target_pub = self.create_publisher(Float32MultiArray, 'vision/target_bbox', 10)

        # 摄像头和模型
        self.cap: Optional[cv2.VideoCapture] = None
        self.bridge = CvBridge() if CvBridge is not None else None
        self.latest_frame = None
        self.last_retry_time = self.get_clock().now()
        self.last_log_time = self.get_clock().now()
        self.image_sub = None

        # 加载 RKNN 模型
        self.rknn = None
        self.use_rknn = False
        
        if RKNN_AVAILABLE:
            try:
                self._load_rknn_model()
                self.use_rknn = True
                self.get_logger().info(f'✓ RKNN 模型加载成功: {self.model_path}')
            except Exception as e:
                self.get_logger().warn(f'RKNN 模型加载失败: {e}，使用肤色检测')
        else:
            # 尝试检查 RKNN 工具包
            self.get_logger().info('RKNN 工具包未找到，使用肤色检测')

        # 图像输入
        if self.camera_test_mode:
            if self.bridge is None:
                raise RuntimeError('cv_bridge not installed')
            self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        else:
            self._open_camera()

        timer_period = 1.0 / max(self.inference_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        mode = '✓ RKNN RetinaFace' if self.use_rknn else '肤色检测'
        self.get_logger().info(f'detection node ready [{mode}]')

    def _load_rknn_model(self) -> None:
        """加载 RKNN 模型。"""
        from pathlib import Path
        
        model_path = Path(self.model_path)
        
        # 搜索模型
        search_paths = [
            model_path,
            Path('/home/radxa/MyDroid/ros2_ws/src/visual_following_car/models') / model_path.name,
            Path('/home/radxa/MyDroid') / model_path.name,
        ]
        
        actual_path = None
        for p in search_paths:
            if p.exists():
                actual_path = p
                break
        
        if not actual_path:
            raise FileNotFoundError(f'Model not found: {self.model_path}')
        
        self.rknn = RKNN(verbose=False)
        self.rknn.load_rknn(str(actual_path))
        self.rknn.init_runtime()

    def _open_camera(self) -> None:
        source = int(self.camera_device) if self.camera_device.isdigit() else self.camera_device
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.camera_device}')
            self.cap = None
            return
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.camera_fps)

    def image_callback(self, msg: Image) -> None:
        try:
            if self.bridge:
                self.latest_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Image conversion failed: {e}')

    def detect_rknn(self, frame: np.ndarray) -> list[dict]:
        """RKNN RetinaFace 检测。"""
        if not self.rknn or frame.size == 0:
            return []
        try:
            h, w = frame.shape[:2]
            img_resized = cv2.resize(frame, (self.input_size, self.input_size))
            outputs = self.rknn.inference([img_resized])
            return self._parse_outputs(outputs, w, h)
        except Exception as e:
            self.get_logger().debug(f'RKNN inference failed: {e}')
            return []

    def _parse_outputs(self, outputs, w: int, h: int) -> list[dict]:
        """解析 RKNN 输出。"""
        detections = []
        try:
            if len(outputs) < 2:
                return detections
            
            locations = outputs[0]
            confidences = outputs[1]
            scale_x, scale_y = w / self.input_size, h / self.input_size
            
            for i in range(len(locations)):
                conf = confidences[i][0] if confidences[i].ndim > 0 else confidences[i]
                if conf < self.confidence_threshold:
                    continue
                
                loc = locations[i]
                x1, y1, x2, y2 = loc[0] * scale_x, loc[1] * scale_y, loc[2] * scale_x, loc[3] * scale_y
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                width, height = x2 - x1, y2 - y1
                
                detections.append({
                    'cx': cx, 'cy': cy, 'w': width, 'h': height,
                    'conf': float(conf), 'area': width * height,
                })
        except Exception as e:
            self.get_logger().debug(f'Parse outputs failed: {e}')
        return detections

    def detect_skin(self, frame: np.ndarray) -> list[dict]:
        """肤色检测。"""
        if not frame.size:
            return []
        
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 20, 70), (20, 255, 255))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections = []
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 500:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            cx, cy = x + w / 2, y + h / 2
            conf = min(1.0, area / 10000.0)
            if conf >= self.confidence_threshold:
                detections.append({'cx': cx, 'cy': cy, 'w': w, 'h': h, 'conf': conf, 'area': area})
        
        return detections

    def timer_callback(self) -> None:
        frame = self.latest_frame if self.camera_test_mode else (
            self.cap.read()[1] if self.cap and self.cap.isOpened() else None
        )
        
        if frame is None or not frame.size:
            if not self.camera_test_mode and (not self.cap or not self.cap.isOpened()):
                now = self.get_clock().now()
                if (now - self.last_retry_time).nanoseconds / 1e9 > self.camera_retry_sec:
                    self._open_camera()
                    self.last_retry_time = now
            return

        # 检测
        detections = self.detect_rknn(frame) if self.use_rknn else self.detect_skin(frame)
        best_det = max(detections, key=lambda d: d['area']) if detections else None

        # 发布
        msg = Float32MultiArray()
        if best_det:
            distance = (self.target_real_height_m * self.camera_focal_length_px) / best_det['h'] if best_det['h'] > 0 else 999.0
            distance = max(0.1, min(distance, 50.0))
            msg.data = [float(best_det['cx']), float(best_det['cy']), float(best_det['w']), float(best_det['h']), float(best_det['conf']), float(distance)]
            
            now = self.get_clock().now()
            if (now - self.last_log_time).nanoseconds / 1e9 > self.log_interval_sec:
                self.get_logger().info(f'Detection: cx={best_det["cx"]:.0f} cy={best_det["cy"]:.0f} conf={best_det["conf"]:.2f} dist={distance:.2f}m')
                self.last_log_time = now
        elif self.publish_no_target:
            msg.data = [float('nan')] * 6

        self.target_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YoloDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.rknn:
            node.rknn.release()
        if node.cap:
            node.cap.release()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
