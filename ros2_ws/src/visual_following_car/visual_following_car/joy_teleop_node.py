#!/usr/bin/env python3
"""手柄遥控节点。

文件职责：
1. 订阅 `sensor_msgs/msg/Joy`，读取蓝牙手柄输入。
2. 在手动模式下输出底盘速度 `teleop/cmd_vel`。
3. 输出手动 Pan 云台控制命令 `teleop/gimbal_cmd`。
4. 管理自动模式开关、急停开关、云台使能开关。

设计原则：
- 节点只负责“人机输入解释”，不负责视觉计算，也不直接碰串口。
- 所有关键参数都通过 ROS2 参数服务器加载，便于不同手柄快速适配。
"""

from __future__ import annotations

from typing import List, Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import Joy
from std_msgs.msg import Bool, Float64MultiArray

from .common import GimbalCommand, apply_deadzone, clamp, slew_limit


class JoyTeleopNode(Node):
    """将蓝牙手柄输入转换为底盘速度和 Pan 云台控制命令。"""

    def __init__(self) -> None:
        """初始化节点、声明参数、创建订阅器/发布器和定时器。"""
        super().__init__('joy_teleop_node')

        # 参数声明区：
        # 这里列出所有可能需要调节的行为，便于通过 YAML 覆盖。
        self.declare_parameters(
            namespace='',
            parameters=[
                ('publish_rate_hz', 30.0),
                ('joy_timeout_sec', 0.5),
                ('deadzone', 0.12),
                ('start_in_auto_mode', False),
                ('estop_latched', True),
                ('max_linear_x_mps', 0.8),
                ('max_linear_y_mps', 0.6),
                ('max_angular_z_radps', 1.2),
                ('max_pan_rate_deg_s', 120.0),
                ('pan_min_deg', 0.0),
                ('pan_max_deg', 180.0),
                ('pan_neutral_deg', 90.0),
                ('axes.linear_x', 1),
                ('axes.linear_y', 0),
                ('axes.angular_z', 3),
                ('axes.gimbal_pan', 6),
                ('buttons.mode_toggle', 0),
                ('buttons.estop', 1),
                ('buttons.gimbal_enable_toggle', 2),
                ('buttons.recenter_gimbal', 3),
                ('gimbal.pan_enabled', True),
                ('gimbal.pan_neutral', 90.0),
                ('gimbal.pan_max_angle', 160.0),
            ],
        )

        # 读取参数并缓存到成员变量，避免在高频回调中重复查询参数服务器。
        self.publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)
        self.joy_timeout_sec = float(self.get_parameter('joy_timeout_sec').value)
        self.deadzone = float(self.get_parameter('deadzone').value)
        self.estop_latched = bool(self.get_parameter('estop_latched').value)
        self.max_linear_x_mps = float(self.get_parameter('max_linear_x_mps').value)
        self.max_linear_y_mps = float(self.get_parameter('max_linear_y_mps').value)
        self.max_angular_z_radps = float(self.get_parameter('max_angular_z_radps').value)
        self.max_pan_rate_deg_s = float(self.get_parameter('max_pan_rate_deg_s').value)
        self.pan_min_deg = float(self.get_parameter('pan_min_deg').value)
        self.pan_max_deg = min(
            float(self.get_parameter('pan_max_deg').value),
            float(self.get_parameter('gimbal.pan_max_angle').value),
        )
        self.pan_neutral_deg = float(self.get_parameter('gimbal.pan_neutral').value)

        # 手柄轴映射：不同型号手柄的轴编号可能不同，因此必须参数化。
        self.axes_linear_x = int(self.get_parameter('axes.linear_x').value)
        self.axes_linear_y = int(self.get_parameter('axes.linear_y').value)
        self.axes_angular_z = int(self.get_parameter('axes.angular_z').value)
        self.axes_gimbal_pan = int(self.get_parameter('axes.gimbal_pan').value)

        # 手柄按键映射：用于模式切换、急停和云台控制。
        self.button_mode_toggle = int(self.get_parameter('buttons.mode_toggle').value)
        self.button_estop = int(self.get_parameter('buttons.estop').value)
        self.button_gimbal_enable_toggle = int(self.get_parameter('buttons.gimbal_enable_toggle').value)
        self.button_recenter_gimbal = int(self.get_parameter('buttons.recenter_gimbal').value)

        # 运行状态变量：这些变量会在回调和定时器之间共享。
        self.auto_mode = bool(self.get_parameter('start_in_auto_mode').value)
        self.estop_active = False
        self.gimbal_pan_enabled = bool(self.get_parameter('gimbal.pan_enabled').value)
        self.manual_pan_deg = self.pan_neutral_deg

        self.latest_joy: Optional[Joy] = None
        self.prev_buttons: List[int] = []
        self.last_joy_time = self.get_clock().now()
        self.last_timer_time = self.get_clock().now()

        # 订阅器：接收 joy_node 发布的手柄数据。
        self.joy_sub = self.create_subscription(Joy, 'joy', self.joy_callback, 20)

        # 发布器：分别输出手动底盘命令、手动云台命令和状态量。
        self.teleop_cmd_pub = self.create_publisher(Twist, 'teleop/cmd_vel', 10)
        self.teleop_gimbal_pub = self.create_publisher(Float64MultiArray, 'teleop/gimbal_cmd', 10)
        self.auto_mode_pub = self.create_publisher(Bool, 'auto_mode', 10)
        self.estop_pub = self.create_publisher(Bool, 'emergency_stop', 10)
        self.gimbal_enable_pub = self.create_publisher(Bool, 'gimbal_pan_enabled', 10)

        # 定时器：固定频率发布控制命令，避免输出仅在按键变化时更新。
        timer_period = 1.0 / max(self.publish_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'Joystick teleop ready: auto_mode={self.auto_mode} '
            f'pan_enabled={self.gimbal_pan_enabled} '
            f'pan_neutral={self.pan_neutral_deg:.1f} pan_max={self.pan_max_deg:.1f}'
        )

    def joy_callback(self, msg: Joy) -> None:
        """处理手柄消息。

        主要职责：
        1. 缓存最新的摇杆轴值和按键值。
        2. 检测按键上升沿，执行模式切换。
        3. 处理急停、云台使能切换和回中命令。

        注意：
        - 这里不直接发布速度，而是只更新状态。
        - 真正的周期性输出在 `timer_callback()` 中统一完成。
        """
        try:
            self.latest_joy = msg
            self.last_joy_time = self.get_clock().now()

            # 切换手动 / 自动模式。
            if self._button_pressed(msg.buttons, self.button_mode_toggle):
                self.auto_mode = not self.auto_mode
                self.get_logger().info(
                    f"Mode switched to {'AUTO' if self.auto_mode else 'MANUAL'}"
                )

            # 急停按钮：如果配置为锁存模式，则按一次切换一次状态。
            if self._button_pressed(msg.buttons, self.button_estop):
                if self.estop_latched:
                    self.estop_active = not self.estop_active
                else:
                    self.estop_active = True
                self.get_logger().warning(
                    f"Emergency stop {'ACTIVE' if self.estop_active else 'CLEARED'}"
                )

            # 云台使能切换：关闭时会自动回中。
            if self._button_pressed(msg.buttons, self.button_gimbal_enable_toggle):
                self.gimbal_pan_enabled = not self.gimbal_pan_enabled
                if not self.gimbal_pan_enabled:
                    self.manual_pan_deg = self.pan_neutral_deg
                self.get_logger().info(
                    f"Pan gimbal {'ENABLED' if self.gimbal_pan_enabled else 'DISABLED'}"
                )

            # 手动一键回中。
            if self._button_pressed(msg.buttons, self.button_recenter_gimbal):
                self.manual_pan_deg = self.pan_neutral_deg
                self.get_logger().info('Pan gimbal re-centered.')

            # 非锁存急停模式下，按钮松开后自动解除急停。
            if not self.estop_latched and self._button_released(msg.buttons, self.button_estop):
                self.estop_active = False

            self.prev_buttons = list(msg.buttons)
        except Exception as exc:
            self.get_logger().error(f'joy_callback failed: {exc}')

    def timer_callback(self) -> None:
        """按固定周期发布手动底盘速度、Pan 云台角度和状态量。

        这样设计的好处：
        - 手柄消息即使暂时停止变化，也能持续维持当前输出。
        - 可以方便加入超时机制、回中逻辑和统一限幅。
        """
        try:
            now = self.get_clock().now()
            dt = max((now - self.last_timer_time).nanoseconds / 1e9, 1.0 / max(self.publish_rate_hz, 1.0))
            self.last_timer_time = now

            # 判断手柄消息是否仍然“新鲜”。
            # 一旦超时，就视作手柄断开或数据卡住，立即输出安全值。
            joy_fresh = ((now - self.last_joy_time).nanoseconds / 1e9) <= self.joy_timeout_sec
            axes = self.latest_joy.axes if joy_fresh and self.latest_joy is not None else []

            twist = Twist()
            if joy_fresh and not self.auto_mode and not self.estop_active:
                # 线速度 / 横移速度 / 角速度均由摇杆轴值线性映射得到。
                twist.linear.x = self._axis_value(axes, self.axes_linear_x) * self.max_linear_x_mps
                twist.linear.y = self._axis_value(axes, self.axes_linear_y) * self.max_linear_y_mps
                twist.angular.z = self._axis_value(axes, self.axes_angular_z) * self.max_angular_z_radps

                # 手动 Pan 云台控制：只在云台使能时才允许改变角度。
                if self.gimbal_pan_enabled:
                    pan_axis = self._axis_value(axes, self.axes_gimbal_pan)
                    self.manual_pan_deg += pan_axis * self.max_pan_rate_deg_s * dt

            # 若云台未使能，则缓慢回中，而不是瞬间跳回中位。
            if not self.gimbal_pan_enabled:
                self.manual_pan_deg = slew_limit(
                    self.pan_neutral_deg,
                    self.manual_pan_deg,
                    self.max_pan_rate_deg_s * dt,
                )

            # 所有输出在发布前必须经过限位。
            self.manual_pan_deg = clamp(self.manual_pan_deg, self.pan_min_deg, self.pan_max_deg)

            # 急停或手柄超时时，底盘速度强制清零。
            if self.estop_active or not joy_fresh:
                twist = Twist()

            gimbal_command = GimbalCommand(
                pan_deg=self.manual_pan_deg,
                enabled=self.gimbal_pan_enabled,
            ).clamped(self.pan_neutral_deg, self.pan_min_deg, self.pan_max_deg)

            gimbal_msg = Float64MultiArray()
            gimbal_msg.data = gimbal_command.to_array(
                self.pan_neutral_deg,
                self.pan_min_deg,
                self.pan_max_deg,
            )

            # 将布尔状态分别发布出来，供其他节点直接订阅。
            auto_mode_msg = Bool()
            auto_mode_msg.data = self.auto_mode
            estop_msg = Bool()
            estop_msg.data = self.estop_active
            gimbal_enable_msg = Bool()
            gimbal_enable_msg.data = self.gimbal_pan_enabled

            self.teleop_cmd_pub.publish(twist)
            self.teleop_gimbal_pub.publish(gimbal_msg)
            self.auto_mode_pub.publish(auto_mode_msg)
            self.estop_pub.publish(estop_msg)
            self.gimbal_enable_pub.publish(gimbal_enable_msg)
        except Exception as exc:
            self.get_logger().error(f'timer_callback failed: {exc}')

    def _button_pressed(self, buttons: List[int], index: int) -> bool:
        """检测指定按键是否发生了“上升沿”。

        上升沿表示：
        - 上一个周期是 0
        - 当前周期是 1

        用这个辅助函数可以避免一个按钮按住不放时被重复触发多次。
        """
        if index < 0 or index >= len(buttons):
            return False
        previous = self.prev_buttons[index] if index < len(self.prev_buttons) else 0
        return buttons[index] == 1 and previous == 0

    def _button_released(self, buttons: List[int], index: int) -> bool:
        """检测指定按键是否发生了“下降沿”。"""
        if index < 0 or index >= len(buttons):
            return False
        previous = self.prev_buttons[index] if index < len(self.prev_buttons) else 0
        return buttons[index] == 0 and previous == 1

    def _axis_value(self, axes: List[float], index: int) -> float:
        """读取摇杆某一轴的值，并执行死区与限幅处理。"""
        if index < 0 or index >= len(axes):
            return 0.0
        return clamp(apply_deadzone(float(axes[index]), self.deadzone), -1.0, 1.0)


def main(args: Optional[list] = None) -> None:
    """节点入口函数。"""
    rclpy.init(args=args)
    node = JoyTeleopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()