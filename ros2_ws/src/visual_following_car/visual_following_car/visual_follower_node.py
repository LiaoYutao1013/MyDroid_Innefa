#!/usr/bin/env python3
"""视觉跟随核心节点。

文件职责：
1. 订阅 YOLO 检测结果 `vision/target_bbox`。
2. 根据目标水平偏差计算 Pan 云台角度。
3. 根据目标中心位置和估计距离计算底盘速度。
4. 在自动模式下发布 `auto/cmd_vel` 和 `auto/gimbal_cmd`。
5. 在相机测试模式下发布虚拟 `/cmd_vel` 和 `/gimbal_cmd` 供调试。

当前版本只做 Pan 方向云台控制，不再做 Tilt 控制。
"""

from __future__ import annotations

import math
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, Float32MultiArray, Float64MultiArray

from .common import GimbalCommand, clamp, slew_limit


class VisualFollowerNode(Node):
    """视觉跟随控制器，仅保留 Pan 方向云台控制。"""

    def __init__(self) -> None:
        """初始化参数、订阅器、发布器和控制状态。"""
        super().__init__('visual_follower_node')

        # 参数区：
        # 这里把视觉跟随所需的所有关键控制量都暴露为 ROS 参数，
        # 方便后续在 YAML 中联调，而不用改代码。
        self.declare_parameters(
            namespace='',
            parameters=[
                ('control_rate_hz', 20.0),
                ('camera_test_mode', False),
                ('camera_test_log_interval_sec', 1.0),
                ('target_timeout_sec', 0.5),
                ('target_distance_m', 1.5),
                ('distance_kp', 0.8),
                ('strafe_kp', 1.1),
                ('omega_from_pan_kp', 1.3),
                ('max_linear_x_mps', 0.8),
                ('max_linear_y_mps', 0.6),
                ('max_angular_z_radps', 1.2),
                ('max_linear_accel_mps2', 1.2),
                ('max_lateral_accel_mps2', 1.2),
                ('max_angular_accel_radps2', 2.0),
                ('pan_min_deg', 0.0),
                ('pan_max_deg', 180.0),
                ('recenter_rate_deg_s', 50.0),
                ('gimbal.pan_enabled', True),
                ('gimbal.pan_neutral', 90.0),
                ('gimbal.pan_kp', 0.8),
                ('gimbal.pan_max_angle', 160.0),
            ],
        )

        # 读取参数。
        self.control_rate_hz = float(self.get_parameter('control_rate_hz').value)
        self.camera_test_mode = bool(self.get_parameter('camera_test_mode').value)
        self.camera_test_log_interval_sec = float(self.get_parameter('camera_test_log_interval_sec').value)
        self.target_timeout_sec = float(self.get_parameter('target_timeout_sec').value)
        self.target_distance_m = float(self.get_parameter('target_distance_m').value)
        self.distance_kp = float(self.get_parameter('distance_kp').value)
        self.strafe_kp = float(self.get_parameter('strafe_kp').value)
        self.omega_from_pan_kp = float(self.get_parameter('omega_from_pan_kp').value)
        self.max_linear_x_mps = float(self.get_parameter('max_linear_x_mps').value)
        self.max_linear_y_mps = float(self.get_parameter('max_linear_y_mps').value)
        self.max_angular_z_radps = float(self.get_parameter('max_angular_z_radps').value)
        self.max_linear_accel_mps2 = float(self.get_parameter('max_linear_accel_mps2').value)
        self.max_lateral_accel_mps2 = float(self.get_parameter('max_lateral_accel_mps2').value)
        self.max_angular_accel_radps2 = float(self.get_parameter('max_angular_accel_radps2').value)
        self.pan_min_deg = float(self.get_parameter('pan_min_deg').value)
        self.pan_max_deg = min(
            float(self.get_parameter('pan_max_deg').value),
            float(self.get_parameter('gimbal.pan_max_angle').value),
        )
        self.recenter_rate_deg_s = float(self.get_parameter('recenter_rate_deg_s').value)
        self.gimbal_pan_enabled = bool(self.get_parameter('gimbal.pan_enabled').value)
        self.gimbal_pan_neutral = float(self.get_parameter('gimbal.pan_neutral').value)
        self.gimbal_pan_kp = float(self.get_parameter('gimbal.pan_kp').value)

        # 控制状态变量。
        self.pan_deg = self.gimbal_pan_neutral
        self.auto_mode = self.camera_test_mode
        self.estop_active = False
        self.current_cmd = Twist()
        self.latest_target: Optional[list] = None
        self.last_target_time = self.get_clock().now()
        self.last_loop_time = self.get_clock().now()
        self.last_camera_test_log_time = self.get_clock().now()

        # 输入订阅：视觉目标、模式状态、急停状态、云台使能状态。
        self.target_sub = self.create_subscription(Float32MultiArray, 'vision/target_bbox', self.target_callback, 10)
        self.auto_mode_sub = self.create_subscription(Bool, 'auto_mode', self.auto_mode_callback, 10)
        self.estop_sub = self.create_subscription(Bool, 'emergency_stop', self.estop_callback, 10)
        self.gimbal_enable_sub = self.create_subscription(Bool, 'gimbal_pan_enabled', self.gimbal_enable_callback, 10)

        # 输出发布器：
        # 正常工作时发布到 auto/* 话题；
        # camera_test_mode 时发布到虚拟调试话题，避免驱动真实硬件。
        self.auto_cmd_pub = self.create_publisher(Twist, 'auto/cmd_vel', 10)
        self.auto_gimbal_pub = self.create_publisher(Float64MultiArray, 'auto/gimbal_cmd', 10)
        self.virtual_cmd_pub = self.create_publisher(Float64MultiArray, '/cmd_vel', 10)
        self.virtual_gimbal_pub = self.create_publisher(Float64MultiArray, '/gimbal_cmd', 10)

        timer_period = 1.0 / max(self.control_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'Visual follower ready: camera_test_mode={self.camera_test_mode} '
            f'pan_enabled={self.gimbal_pan_enabled} '
            f'pan_neutral={self.gimbal_pan_neutral:.1f} '
            f'pan_kp={self.gimbal_pan_kp:.3f} pan_max={self.pan_max_deg:.1f}'
        )

    def target_callback(self, msg: Float32MultiArray) -> None:
        """缓存最新的目标检测结果。

        输入格式约定：
        - data[0]: 目标中心 x 的归一化坐标。
        - data[1]: 目标中心 y 的归一化坐标。
        - data[6]: 近似距离（米）。

        如果数组长度不足，说明当前没有有效目标。
        """
        try:
            if len(msg.data) < 7:
                self.latest_target = None
                return
            self.latest_target = list(msg.data)
            self.last_target_time = self.get_clock().now()
        except Exception as exc:
            self.get_logger().error(f'target_callback failed: {exc}')

    def auto_mode_callback(self, msg: Bool) -> None:
        """更新自动模式状态。"""
        try:
            self.auto_mode = bool(msg.data)
        except Exception as exc:
            self.get_logger().error(f'auto_mode_callback failed: {exc}')

    def estop_callback(self, msg: Bool) -> None:
        """更新急停状态。"""
        try:
            self.estop_active = bool(msg.data)
        except Exception as exc:
            self.get_logger().error(f'estop_callback failed: {exc}')

    def gimbal_enable_callback(self, msg: Bool) -> None:
        """更新云台使能状态。

        当外部将云台禁用时，这里立即把当前 pan 角度重置为中位，
        保证后续发布出去的云台命令稳定可预期。
        """
        try:
            self.gimbal_pan_enabled = bool(msg.data)
            if not self.gimbal_pan_enabled:
                self.pan_deg = self.gimbal_pan_neutral
        except Exception as exc:
            self.get_logger().error(f'gimbal_enable_callback failed: {exc}')

    def timer_callback(self) -> None:
        """按固定频率运行视觉跟随控制。

        控制流程概述：
        1. 判断当前是否允许进入自动控制。
        2. 检查目标是否仍在超时窗口内。
        3. 根据目标水平偏差计算目标 pan 角度。
        4. 根据目标距离和横向偏差计算底盘速度。
        5. 对底盘速度做加速度限制。
        6. 发布到真实控制话题或相机测试话题。
        """
        try:
            now = self.get_clock().now()
            dt = max((now - self.last_loop_time).nanoseconds / 1e9, 1e-3)
            self.last_loop_time = now

            auto_enabled = self.auto_mode or self.camera_test_mode
            target_is_fresh = ((now - self.last_target_time).nanoseconds / 1e9) <= self.target_timeout_sec
            target_twist = Twist()
            target_pan_deg = self.gimbal_pan_neutral
            target_text = 'no target'

            if auto_enabled and not self.estop_active and target_is_fresh and self.latest_target is not None:
                center_x = float(self.latest_target[0])
                approx_distance_m = float(self.latest_target[6])
                horizontal_error = 0.5 - center_x
                target_text = f'({center_x:.3f})'

                if self.gimbal_pan_enabled:
                    # 简单 P 控制：
                    # 目标越偏离画面水平中心，Pan 修正越大。
                    # 这里乘以 180.0 是为了把归一化误差放大到角度量级。
                    target_pan_deg = self.gimbal_pan_neutral + (horizontal_error * self.gimbal_pan_kp * 180.0)
                    target_pan_deg = clamp(target_pan_deg, self.pan_min_deg, self.pan_max_deg)

                if approx_distance_m > 0.0:
                    # 前后跟随：当前估计距离大于目标距离时前进，小于目标距离时后退。
                    distance_error = approx_distance_m - self.target_distance_m
                    target_twist.linear.x = clamp(
                        self.distance_kp * distance_error,
                        -self.max_linear_x_mps,
                        self.max_linear_x_mps,
                    )

                # 左右横移：目标偏左则底盘向左移动，偏右则向右移动。
                target_twist.linear.y = clamp(
                    -self.strafe_kp * (center_x - 0.5),
                    -self.max_linear_y_mps,
                    self.max_linear_y_mps,
                )
            else:
                target_pan_deg = self.gimbal_pan_neutral

            # 如果云台功能被禁用，则无条件回中。
            if not self.gimbal_pan_enabled:
                target_pan_deg = self.gimbal_pan_neutral

            # 使用 slew_limit 让 Pan 角变化更平滑，保护舵机与结构件。
            self.pan_deg = slew_limit(
                target_pan_deg,
                self.pan_deg,
                self.recenter_rate_deg_s * dt,
            )
            self.pan_deg = clamp(self.pan_deg, self.pan_min_deg, self.pan_max_deg)

            # 当云台偏离中位时，让底盘缓慢回正，减少云台长期偏转。
            target_twist.angular.z = clamp(
                self.omega_from_pan_kp * math.radians(self.gimbal_pan_neutral - self.pan_deg),
                -self.max_angular_z_radps,
                self.max_angular_z_radps,
            )

            # 对速度做斜率限制，防止输出跳变。
            self.current_cmd.linear.x = slew_limit(
                target_twist.linear.x,
                self.current_cmd.linear.x,
                self.max_linear_accel_mps2 * dt,
            )
            self.current_cmd.linear.y = slew_limit(
                target_twist.linear.y,
                self.current_cmd.linear.y,
                self.max_lateral_accel_mps2 * dt,
            )
            self.current_cmd.angular.z = slew_limit(
                target_twist.angular.z,
                self.current_cmd.angular.z,
                self.max_angular_accel_radps2 * dt,
            )

            # 急停或未启用自动控制时，输出零速度。
            if self.estop_active or not auto_enabled:
                self.current_cmd = Twist()

            gimbal_command = GimbalCommand(
                pan_deg=self.pan_deg,
                enabled=self.gimbal_pan_enabled,
            ).clamped(self.gimbal_pan_neutral, self.pan_min_deg, self.pan_max_deg)

            gimbal_msg = Float64MultiArray()
            gimbal_msg.data = gimbal_command.to_array(
                self.gimbal_pan_neutral,
                self.pan_min_deg,
                self.pan_max_deg,
            )

            if self.camera_test_mode:
                # 相机测试模式下不驱动真实硬件，只把计算结果发布到虚拟话题供调试观察。
                cmd_msg = Float64MultiArray()
                cmd_msg.data = [
                    clamp(self.current_cmd.linear.x, -self.max_linear_x_mps, self.max_linear_x_mps),
                    clamp(self.current_cmd.linear.y, -self.max_linear_y_mps, self.max_linear_y_mps),
                    clamp(self.current_cmd.angular.z, -self.max_angular_z_radps, self.max_angular_z_radps),
                ]
                self.virtual_cmd_pub.publish(cmd_msg)
                self.virtual_gimbal_pub.publish(gimbal_msg)

                if (now - self.last_camera_test_log_time).nanoseconds / 1e9 >= self.camera_test_log_interval_sec:
                    self.last_camera_test_log_time = now
                    self.get_logger().info(
                        '【Camera Test Mode】目标坐标=%s Pan=%.2f 跟随速度=[%.3f, %.3f, %.3f] FPS=%.2f'
                        % (
                            target_text,
                            gimbal_msg.data[0],
                            cmd_msg.data[0],
                            cmd_msg.data[1],
                            cmd_msg.data[2],
                            1.0 / max(dt, 1e-6),
                        )
                    )
            else:
                self.auto_cmd_pub.publish(self.current_cmd)
                self.auto_gimbal_pub.publish(gimbal_msg)
        except Exception as exc:
            self.get_logger().error(f'timer_callback failed: {exc}')


def main(args: Optional[list] = None) -> None:
    """节点入口函数。"""
    rclpy.init(args=args)
    node = VisualFollowerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()