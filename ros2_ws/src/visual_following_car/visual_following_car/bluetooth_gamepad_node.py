#!/usr/bin/env python3
"""
Radxa ROCK 3B 蓝牙手柄驱动节点
支持标准Gamepad和雷神蓝牙手柄

功能：
  - 监听Joy输入
  - 将Joy消息转为Twist速度命令
  - 支持自定义按键映射
  - 提供急停和功能按键处理
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
from sensor_msgs.msg import Joy
from geometry_msgs.msg import Twist
from std_msgs.msg import Float32
import yaml
import os
from pathlib import Path

class BluetoothGamepadNode(Node):
    def __init__(self):
        super().__init__('bluetooth_gamepad_node')

        # 获取配置文件路径
        config_dir = Path.home() / 'MyDroid' / 'ros2_ws' / 'src' / 'visual_following_car' / 'config'
        mapping_file = config_dir / 'gamepad_mapping.yaml'

        # 加载默认映射（如果配置文件不存在）
        self.mapping = self._load_mapping(mapping_file)

        # 声明参数
        self.declare_parameter('max_linear_speed', 0.5)      # m/s
        self.declare_parameter('max_angular_speed', 1.0)     # rad/s
        self.declare_parameter('deadzone', 0.1)              # 摇杆死区
        self.declare_parameter('enable_debug', True)         # 调试输出

        # 读取参数
        self.max_linear_speed = self.get_parameter('max_linear_speed').value
        self.max_angular_speed = self.get_parameter('max_angular_speed').value
        self.deadzone = self.get_parameter('deadzone').value
        self.enable_debug = self.get_parameter('enable_debug').value

        # QoS配置
        qos_profile = QoSProfile(depth=10)
        qos_profile.reliability = QoSReliabilityPolicy.BEST_EFFORT

        # 订阅Joy输入
        self.joy_subscription = self.create_subscription(
            Joy,
            '/joy',
            self.joy_callback,
            qos_profile
        )

        # 发布快速线速度命令
        self.cmd_vel_publisher = self.create_publisher(
            Twist,
            '/cmd_vel',
            10
        )

        # 发布云台Pan角度
        self.gimbal_pan_publisher = self.create_publisher(
            Float32,
            '/gimbal/pan_angle',
            10
        )

        self.get_logger().info(
            f"✓ Bluetooth Gamepad Node Started\n"
            f"  Max Linear Speed: {self.max_linear_speed} m/s\n"
            f"  Max Angular Speed: {self.max_angular_speed} rad/s\n"
            f"  Deadzone: {self.deadzone}\n"
            f"  Debug: {self.enable_debug}"
        )

        # 状态跟踪
        self.last_twist = Twist()
        self.pan_angle = 0.0
        self.auto_mode_enabled = False
        self.emergency_stop = False

    def _load_mapping(self, mapping_file):
        """加载按键映射配置"""
        default_mapping = {
            'buttons': {
                'A': 0, 'B': 1, 'X': 2, 'Y': 3,
                'LB': 4, 'RB': 5,
                'back': 6, 'start': 7,
                'left_stick': 8, 'right_stick': 9,
                'guide': 10
            },
            'axes': {
                'left_stick_x': 0,
                'left_stick_y': 1,
                'left_trigger': 2,
                'right_stick_x': 3,
                'right_stick_y': 4,
                'right_trigger': 5,
                'dpad_x': 6,
                'dpad_y': 7
            },
            'controls': {
                'forward': 'left_stick_y',
                'strafe': 'left_stick_x',
                'rotate': 'right_stick_x',
                'gimbal_pan': 'dpad_x',
                'gimbal_tilt': 'dpad_y',
                'enable_follow': 'start',
                'disable_follow': 'back',
                'estop': 'Y'
            }
        }

        # 尝试加载自定义映射
        if mapping_file.exists():
            try:
                with open(mapping_file, 'r') as f:
                    custom = yaml.safe_load(f)
                if custom and 'gamepad_mapping' in custom:
                    mapping = custom['gamepad_mapping']
                    self.get_logger().info(f"✓ Loaded mapping from {mapping_file}")
                    return mapping
            except Exception as e:
                self.get_logger().warn(f"Failed to load {mapping_file}: {e}")
                self.get_logger().warn("Using default mapping")

        return default_mapping

    def joy_callback(self, msg: Joy):
        """处理Joy消息"""

        if self.enable_debug:
            self._log_joy_input(msg)

        # 检查急停
        if self._check_estop(msg):
            self.emergency_stop = True
            self._send_stop_command()
            return

        # 处理底盘控制
        self._handle_chassis_control(msg)

        # 处理云台控制
        self._handle_gimbal_control(msg)

        # 处理功能按键
        self._handle_function_keys(msg)

    def _check_estop(self, msg: Joy) -> bool:
        """检查急停按键"""
        estop_button = self.mapping['buttons'].get('Y', 3)

        if estop_button < len(msg.buttons) and msg.buttons[estop_button]:
            self.get_logger().warn("🛑 EMERGENCY STOP TRIGGERED!")
            return True

        return False

    def _handle_chassis_control(self, msg: Joy):
        """处理底盘速度控制"""

        if self.emergency_stop:
            self._send_stop_command()
            return

        # 获取摇杆映射
        controls = self.mapping['controls']
        axes_map = self.mapping['axes']

        forward_axis = axes_map.get(controls.get('forward', 'left_stick_y'), 1)
        strafe_axis = axes_map.get(controls.get('strafe', 'left_stick_x'), 0)
        rotate_axis = axes_map.get(controls.get('rotate', 'right_stick_x'), 3)

        # 获取轴值
        forward = self._apply_deadzone(msg.axes[forward_axis]) if forward_axis < len(msg.axes) else 0.0
        strafe = self._apply_deadzone(msg.axes[strafe_axis]) if strafe_axis < len(msg.axes) else 0.0
        rotate = self._apply_deadzone(msg.axes[rotate_axis]) if rotate_axis < len(msg.axes) else 0.0

        # 创建Twist消息
        twist = Twist()
        twist.linear.x = forward * self.max_linear_speed          # 前进/后退
        twist.linear.y = strafe * self.max_linear_speed           # 左平移/右平移
        twist.angular.z = rotate * self.max_angular_speed         # 旋转

        # 只有变化时才发布（减少消息数量）
        if self._twist_changed(twist):
            self.cmd_vel_publisher.publish(twist)
            self.last_twist = twist

            if self.enable_debug:
                self.get_logger().info(
                    f"Cmd: vx={twist.linear.x:.2f} vy={twist.linear.y:.2f} "
                    f"omega={twist.angular.z:.2f}"
                )

    def _handle_gimbal_control(self, msg: Joy):
        """处理云台（Pan/Tilt）控制"""

        controls = self.mapping['controls']
        axes_map = self.mapping['axes']

        # D-Pad用于云台控制
        pan_axis = axes_map.get(controls.get('gimbal_pan', 'dpad_x'), 6)

        if pan_axis < len(msg.axes):
            pan_input = self._apply_deadzone(msg.axes[pan_axis])

            # 更新Pan角度 (±90度范围)
            if abs(pan_input) > 0.1:
                self.pan_angle += pan_input * 5.0  # 每次增量5度
                self.pan_angle = max(-90.0, min(90.0, self.pan_angle))  # 限制在±90度

                pan_msg = Float32()
                pan_msg.data = self.pan_angle
                self.gimbal_pan_publisher.publish(pan_msg)

                if self.enable_debug:
                    self.get_logger().info(f"Pan angle: {self.pan_angle:.1f}°")

    def _handle_function_keys(self, msg: Joy):
        """处理功能按键"""

        controls = self.mapping['controls']
        buttons_map = self.mapping['buttons']

        # enable/disable 按键
        enable_btn = buttons_map.get(controls.get('enable_follow', 'start'), 7)
        disable_btn = buttons_map.get(controls.get('disable_follow', 'back'), 6)

        if enable_btn < len(msg.buttons) and msg.buttons[enable_btn]:
            if not self.auto_mode_enabled:
                self.auto_mode_enabled = True
                self.get_logger().info("✓ Auto follow mode ENABLED")
                self.emergency_stop = False

        if disable_btn < len(msg.buttons) and msg.buttons[disable_btn]:
            if self.auto_mode_enabled:
                self.auto_mode_enabled = False
                self.get_logger().info("✗ Auto follow mode DISABLED")
                self._send_stop_command()

    def _apply_deadzone(self, value: float) -> float:
        """应用死区处理"""
        if abs(value) < self.deadzone:
            return 0.0

        # 扩展死区段
        if value > 0:
            return (value - self.deadzone) / (1.0 - self.deadzone)
        else:
            return (value + self.deadzone) / (1.0 - self.deadzone)

    def _twist_changed(self, new_twist: Twist) -> bool:
        """检查Twist是否有意义的改变"""
        threshold = 0.01

        return (
            abs(new_twist.linear.x - self.last_twist.linear.x) > threshold or
            abs(new_twist.linear.y - self.last_twist.linear.y) > threshold or
            abs(new_twist.angular.z - self.last_twist.angular.z) > threshold
        )

    def _send_stop_command(self):
        """发送停止命令"""
        twist = Twist()
        self.cmd_vel_publisher.publish(twist)
        self.last_twist = twist

    def _log_joy_input(self, msg: Joy):
        """记录Joy输入（调试用）"""
        # 检查是否有非零输入
        has_button = any(msg.buttons)
        has_axis = any(abs(a) > self.deadzone for a in msg.axes)

        if has_button or has_axis:
            button_str = ', '.join([str(i) for i, b in enumerate(msg.buttons) if b])
            axis_str = ', '.join([f"{i}:{a:.2f}" for i, a in enumerate(msg.axes) if abs(a) > self.deadzone])

            if button_str:
                self.get_logger().debug(f"Buttons: {button_str}")
            if axis_str:
                self.get_logger().debug(f"Axes: {axis_str}")


def main(args=None):
    rclpy.init(args=args)
    node = BluetoothGamepadNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
