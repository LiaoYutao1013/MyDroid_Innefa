#!/usr/bin/env python3
"""视觉目标检测节点。

当前输出协议统一为：
`[cx_norm, cy_norm, w_norm, h_norm, confidence, area_norm, distance_m, image_w, image_h]`

字段说明：
1. `cx_norm` / `cy_norm`：目标中心点的归一化坐标，范围通常为 0.0 ~ 1.0;
2. `w_norm` / `h_norm`：目标框宽高的归一化尺寸；
3. `confidence`：检测置信度；
4. `area_norm`：目标框面积占整幅图像面积的比例；
5. `distance_m`：基于目标高度估算的近似距离；
6. `image_w` / `image_h`：产生该检测结果时的图像尺寸，便于下游节点做像素反算。

当前节点优先尝试使用 RKNN RetinaFace;若 RKNN 环境不可用，则自动降级为肤色区域检测。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

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

try:
    from rknn.api import RKNN
    RKNN_AVAILABLE = True
except ImportError:
    RKNN_AVAILABLE = False


class YoloDetectionNode(Node):
    """统一发布视觉目标框协议的检测节点。"""

    def __init__(self) -> None:
        super().__init__('yolo_detection_node')

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

        self.target_pub = self.create_publisher(Float32MultiArray, 'vision/target_bbox', 10)

        self.cap: Optional[cv2.VideoCapture] = None
        self.bridge = CvBridge() if CvBridge is not None else None
        self.latest_frame: Optional[np.ndarray] = None
        self.last_retry_time = self.get_clock().now()
        self.last_log_time = self.get_clock().now()
        self.image_sub = None

        self.rknn = None
        self.use_rknn = False

        if RKNN_AVAILABLE:
            try:
                self._load_rknn_model()
                self.use_rknn = True
                self.get_logger().info(f'RKNN 模型加载成功: {self.model_path}')
            except Exception as exc:
                self.get_logger().warning(f'RKNN 模型加载失败，改用肤色检测: {exc}')
        else:
            self.get_logger().info('未检测到 RKNN 运行环境，改用肤色检测')

        if self.camera_test_mode:
            if self.bridge is None:
                raise RuntimeError('cv_bridge not installed')
            self.image_sub = self.create_subscription(Image, self.image_topic, self.image_callback, 10)
        else:
            self._open_camera()

        timer_period = 1.0 / max(self.inference_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        mode = 'RKNN RetinaFace' if self.use_rknn else '肤色检测'
        self.get_logger().info(f'detection node ready [{mode}]')

    def _load_rknn_model(self) -> None:
        model_path = Path(self.model_path)
        search_paths = [
            model_path,
            Path('/home/radxa/MyDroid/ros2_ws/src/visual_following_car/models') / model_path.name,
            Path('/home/radxa/MyDroid') / model_path.name,
        ]

        actual_path = next((path for path in search_paths if path.exists()), None)
        if actual_path is None:
            raise FileNotFoundError(f'model not found: {self.model_path}')

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
            if self.bridge is not None:
                self.latest_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as exc:
            self.get_logger().error(f'Image conversion failed: {exc}')

    def detect_rknn(self, frame: np.ndarray) -> list[dict]:
        if self.rknn is None or frame.size == 0:
            return []

        try:
            frame_h, frame_w = frame.shape[:2]
            resized = cv2.resize(frame, (self.input_size, self.input_size))
            outputs = self.rknn.inference([resized])
            return self._parse_outputs(outputs, frame_w, frame_h)
        except Exception as exc:
            self.get_logger().debug(f'RKNN inference failed: {exc}')
            return []

    def _parse_outputs(self, outputs, frame_w: int, frame_h: int) -> list[dict]:
        detections: list[dict] = []
        if len(outputs) < 2:
            return detections

        try:
            locations = outputs[0]
            confidences = outputs[1]
            scale_x = frame_w / float(self.input_size)
            scale_y = frame_h / float(self.input_size)

            for loc, conf_value in zip(locations, confidences):
                confidence = float(conf_value[0] if np.ndim(conf_value) > 0 else conf_value)
                if confidence < self.confidence_threshold:
                    continue

                x1 = float(loc[0]) * scale_x
                y1 = float(loc[1]) * scale_y
                x2 = float(loc[2]) * scale_x
                y2 = float(loc[3]) * scale_y
                width = max(0.0, x2 - x1)
                height = max(0.0, y2 - y1)

                detections.append(
                    {
                        'cx': (x1 + x2) / 2.0,
                        'cy': (y1 + y2) / 2.0,
                        'w': width,
                        'h': height,
                        'conf': confidence,
                        'area': width * height,
                    }
                )
        except Exception as exc:
            self.get_logger().debug(f'Parse outputs failed: {exc}')

        return detections

    def detect_skin(self, frame: np.ndarray) -> list[dict]:
        if frame.size == 0:
            return []

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 20, 70), (20, 255, 255))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: list[dict] = []

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < 500.0:
                continue

            x, y, width, height = cv2.boundingRect(contour)
            confidence = min(1.0, area / 10000.0)
            if confidence < self.confidence_threshold:
                continue

            detections.append(
                {
                    'cx': x + (width / 2.0),
                    'cy': y + (height / 2.0),
                    'w': float(width),
                    'h': float(height),
                    'conf': confidence,
                    'area': area,
                }
            )

        return detections

    def _estimate_distance(self, detection: dict) -> float:
        height_px = max(float(detection['h']), 1.0)
        distance_m = (self.target_real_height_m * self.camera_focal_length_px) / height_px
        return max(0.1, min(distance_m, 50.0))

    def _build_target_message(self, detection: dict, frame_w: int, frame_h: int) -> list[float]:
        frame_area = max(float(frame_w * frame_h), 1.0)

        cx_norm = float(detection['cx']) / float(frame_w)
        cy_norm = float(detection['cy']) / float(frame_h)
        w_norm = float(detection['w']) / float(frame_w)
        h_norm = float(detection['h']) / float(frame_h)
        area_norm = float(detection['area']) / frame_area
        distance_m = self._estimate_distance(detection)

        return [
            float(np.clip(cx_norm, 0.0, 1.0)),
            float(np.clip(cy_norm, 0.0, 1.0)),
            float(np.clip(w_norm, 0.0, 1.0)),
            float(np.clip(h_norm, 0.0, 1.0)),
            float(np.clip(float(detection['conf']), 0.0, 1.0)),
            float(np.clip(area_norm, 0.0, 1.0)),
            distance_m,
            float(frame_w),
            float(frame_h),
        ]

    def timer_callback(self) -> None:
        frame = self.latest_frame if self.camera_test_mode else (
            self.cap.read()[1] if self.cap is not None and self.cap.isOpened() else None
        )

        if frame is None or frame.size == 0:
            if not self.camera_test_mode and (self.cap is None or not self.cap.isOpened()):
                now = self.get_clock().now()
                if (now - self.last_retry_time).nanoseconds / 1e9 > self.camera_retry_sec:
                    self._open_camera()
                    self.last_retry_time = now
            return

        frame_h, frame_w = frame.shape[:2]
        detections = self.detect_rknn(frame) if self.use_rknn else self.detect_skin(frame)
        best_det = max(detections, key=lambda det: det['area']) if detections else None

        msg = Float32MultiArray()
        if best_det is not None:
            msg.data = self._build_target_message(best_det, frame_w, frame_h)

            now = self.get_clock().now()
            if (now - self.last_log_time).nanoseconds / 1e9 > self.log_interval_sec:
                self.get_logger().info(
                    'Detection: cx=%.3f cy=%.3f conf=%.2f dist=%.2fm'
                    % (msg.data[0], msg.data[1], msg.data[4], msg.data[6])
                )
                self.last_log_time = now
        elif self.publish_no_target:
            # 统一使用空数组表达“本周期无目标”，避免下游把 NaN 当作有效数据继续控制。
            msg.data = []
        else:
            return

        self.target_pub.publish(msg)

    def destroy_node(self) -> bool:
        if self.cap is not None:
            self.cap.release()

        if self.rknn is not None and hasattr(self.rknn, 'release'):
            try:
                self.rknn.release()
            except Exception:
                pass

        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = YoloDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
