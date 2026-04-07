#!/usr/bin/env python3
"""YOLOv8 目标检测节点。

文件职责：
1. 从 USB 摄像头或 ROS 图像话题读取图像。
2. 使用 ultralytics YOLOv8 模型进行目标检测。
3. 从多目标中筛选“最适合跟随”的目标。
4. 发布目标框中心、尺寸、置信度和粗略距离估计。

注意：
- 本节点只负责“感知”，不负责底盘或云台控制。
- 视觉跟随逻辑由 `visual_follower_node.py` 完成。
"""

from __future__ import annotations

from typing import Optional, Union

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
    from ultralytics import YOLO
except ImportError as exc:  # pragma: no cover - runtime dependency on target machine
    YOLO = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class YoloDetectionNode(Node):
    """采集图像、执行 YOLO 推理并发布最佳目标框。"""

    def __init__(self) -> None:
        """初始化模型、图像输入源、参数和定时器。"""
        super().__init__('yolo_detection_node')

        if YOLO is None:
            raise RuntimeError(
                'ultralytics is not installed. Install requirements.txt before running.'
            ) from IMPORT_ERROR

        # 参数区：既支持直接读摄像头，也支持 camera_test_mode 下订阅图像话题。
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
                ('model_path', 'yolov8n.pt'),
                ('input_size', 416),
                ('confidence_threshold', 0.45),
                ('iou_threshold', 0.45),
                ('device', 'cpu'),
                ('target_class_names', ['person']),
                ('target_real_height_m', 1.70),
                ('camera_focal_length_px', 650.0),
                ('publish_no_target', True),
                ('log_interval_sec', 1.0),
            ],
        )

        # 读取参数。
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
        self.iou_threshold = float(self.get_parameter('iou_threshold').value)
        self.device = str(self.get_parameter('device').value)
        self.target_class_names = set(self.get_parameter('target_class_names').value)
        self.target_real_height_m = float(self.get_parameter('target_real_height_m').value)
        self.camera_focal_length_px = float(self.get_parameter('camera_focal_length_px').value)
        self.publish_no_target = bool(self.get_parameter('publish_no_target').value)
        self.log_interval_sec = float(self.get_parameter('log_interval_sec').value)

        self.target_pub = self.create_publisher(Float32MultiArray, 'vision/target_bbox', 10)

        # 加载 YOLO 模型。
        self.model = YOLO(self.model_path)

        # 图像输入相关状态。
        self.cap: Optional[cv2.VideoCapture] = None
        self.bridge = CvBridge() if CvBridge is not None else None
        self.latest_frame = None
        self.last_retry_time = self.get_clock().now()
        self.last_inference_time = self.get_clock().now()
        self.last_log_time = self.get_clock().now()
        self.image_sub = None

        if self.camera_test_mode:
            # 在 camera_test_mode 下，不直接打开摄像头，而是等待外部图像话题输入。
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
            f'YOLO detection node ready. camera_test_mode={self.camera_test_mode} '
            f'camera={self.camera_device} image_topic={self.image_topic} '
            f'model={self.model_path} device={self.device} '
            f'conf={self.confidence_threshold} iou={self.iou_threshold}'
        )

    def _open_camera(self) -> None:
        """打开本地摄像头并设置采集参数。"""
        if self.camera_test_mode:
            return

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        source: Union[int, str] = int(self.camera_device) if self.camera_device.isdigit() else self.camera_device
        self.cap = cv2.VideoCapture(source)

        if not self.cap.isOpened():
            self.get_logger().error(f'Failed to open camera: {self.camera_device}')
            self.cap = None
            return

        # 这些参数并不保证驱动一定接受，但会尽量尝试设置。
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        self.cap.set(cv2.CAP_PROP_FPS, self.camera_fps)

    def image_callback(self, msg: Image) -> None:
        """在 camera_test_mode 下缓存最新一帧图像。

        这样 timer_callback 可以按照固定推理频率运行，
        而不是每收到一帧图像就立即推理。
        """
        try:
            if self.bridge is None:
                return
            self.latest_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as exc:
            self.get_logger().error(f'image_callback failed: {exc}')

    def timer_callback(self) -> None:
        """读取一帧图像、执行检测并发布最佳目标。"""
        try:
            now = self.get_clock().now()
            if self.camera_test_mode:
                if self.latest_frame is None:
                    return
                frame = self.latest_frame.copy()
            else:
                if self.cap is None:
                    elapsed = (now - self.last_retry_time).nanoseconds / 1e9
                    if elapsed >= self.camera_retry_sec:
                        self.last_retry_time = now
                        self._open_camera()
                    return

                ok, frame = self.cap.read()
                if not ok or frame is None:
                    self.get_logger().warn('Camera frame grab failed, reopening camera.')
                    self.last_retry_time = now
                    self._open_camera()
                    self._publish_no_target()
                    return

            # YOLO 推理。
            try:
                results = self.model.predict(
                    source=frame,
                    verbose=False,
                    imgsz=self.input_size,
                    conf=self.confidence_threshold,
                    iou=self.iou_threshold,
                    device=self.device,
                )
            except Exception as exc:  # pragma: no cover - hardware/runtime path
                self.get_logger().error(f'YOLO inference failed: {exc}')
                self._publish_no_target()
                return

            result = results[0]
            boxes = result.boxes

            if boxes is None or len(boxes) == 0:
                self._publish_no_target()
                return

            frame_h, frame_w = frame.shape[:2]
            best_candidate = None
            best_area = -1.0
            names = result.names

            # 策略：从所有检测框里挑出“面积最大”的目标作为跟随对象。
            # 对于 person 跟随场景，这通常代表目标离相机更近、也更值得优先跟随。
            for box in boxes:
                cls_id = int(box.cls.item())
                if isinstance(names, dict):
                    cls_name = names.get(cls_id, str(cls_id))
                elif 0 <= cls_id < len(names):
                    cls_name = names[cls_id]
                else:
                    cls_name = str(cls_id)
                if self.target_class_names and cls_name not in self.target_class_names:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].tolist()
                width = max(x2 - x1, 0.0)
                height = max(y2 - y1, 0.0)
                area = width * height

                if area <= best_area:
                    continue

                confidence = float(box.conf.item())
                center_x = (x1 + x2) * 0.5
                center_y = (y1 + y2) * 0.5

                # 简单单目距离估计：
                # 距离 ≈ 真实高度 * 焦距 / 像素高度。
                approx_distance = -1.0
                if height > 1.0 and self.camera_focal_length_px > 0.0:
                    approx_distance = (
                        self.target_real_height_m * self.camera_focal_length_px / height
                    )

                best_candidate = [
                    center_x / max(frame_w, 1),
                    center_y / max(frame_h, 1),
                    width / max(frame_w, 1),
                    height / max(frame_h, 1),
                    confidence,
                    area / max(frame_w * frame_h, 1),
                    approx_distance,
                    float(frame_w),
                    float(frame_h),
                ]
                best_area = area

            if best_candidate is None:
                self._publish_no_target()
                return

            msg = Float32MultiArray()
            msg.data = best_candidate
            self.target_pub.publish(msg)

            # 输出 FPS、置信度和中心坐标，便于现场调试。
            inference_dt = max((now - self.last_inference_time).nanoseconds / 1e9, 1e-6)
            self.last_inference_time = now
            fps = 1.0 / inference_dt
            if (now - self.last_log_time).nanoseconds / 1e9 >= self.log_interval_sec:
                self.last_log_time = now
                self.get_logger().info(
                    f'YOLO FPS={fps:.2f} conf={best_candidate[4]:.2f} '
                    f'center=({best_candidate[0]:.3f}, {best_candidate[1]:.3f})'
                )
        except Exception as exc:
            self.get_logger().error(f'timer_callback failed: {exc}')

    def _publish_no_target(self) -> None:
        """在允许时发布“无目标”消息。"""
        if not self.publish_no_target:
            return
        msg = Float32MultiArray()
        msg.data = []
        self.target_pub.publish(msg)

    def destroy_node(self) -> bool:
        """节点销毁前释放摄像头资源。"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        return super().destroy_node()


def main(args: Optional[list] = None) -> None:
    """节点入口函数。"""
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