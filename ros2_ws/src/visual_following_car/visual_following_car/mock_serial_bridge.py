#!/usr/bin/env python3
"""纯视觉测试模式下使用的 mock 串口桥。

文件职责：
1. 在没有真实 STM32 的情况下，订阅虚拟控制话题。
2. 把视觉跟随计算得到的底盘速度和云台角度打印到终端。
3. 帮助验证视觉控制链路是否正确，而无需接入真实硬件。
"""

from __future__ import annotations

from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64MultiArray


class MockSerialBridgeNode(Node):
    """纯视觉模式下的虚拟串口桥，仅用于打印跟随输出。"""

    def __init__(self) -> None:
        """初始化参数、订阅器和日志节流状态。"""
        super().__init__('mock_serial_bridge')

        self.declare_parameters(
            namespace='',
            parameters=[
                ('camera_test_mode', True),
                ('log_interval_sec', 0.5),
            ],
        )

        self.camera_test_mode = bool(self.get_parameter('camera_test_mode').value)
        self.log_interval_sec = float(self.get_parameter('log_interval_sec').value)
        self.last_log_time = self.get_clock().now()
        self.latest_cmd_vel = [0.0, 0.0, 0.0]
        self.latest_gimbal = [90.0, 90.0]

        self.cmd_sub = self.create_subscription(Float64MultiArray, '/cmd_vel', self.cmd_callback, 10)
        self.gimbal_sub = self.create_subscription(Float64MultiArray, '/gimbal_cmd', self.gimbal_callback, 10)

        self.get_logger().info(
            f'mock_serial_bridge ready: camera_test_mode={self.camera_test_mode}, '
            f'log_interval_sec={self.log_interval_sec}'
        )

    def cmd_callback(self, msg: Float64MultiArray) -> None:
        """接收虚拟底盘速度命令并缓存。"""
        try:
            if not self.camera_test_mode:
                return
            if len(msg.data) >= 3:
                self.latest_cmd_vel = [float(msg.data[0]), float(msg.data[1]), float(msg.data[2])]
                self._maybe_log()
        except Exception as exc:
            self.get_logger().error(f'cmd_callback failed: {exc}')

    def gimbal_callback(self, msg: Float64MultiArray) -> None:
        """接收虚拟云台命令并缓存。"""
        try:
            if not self.camera_test_mode:
                return
            if len(msg.data) >= 2:
                self.latest_gimbal = [float(msg.data[0]), float(msg.data[1])]
                self._maybe_log()
        except Exception as exc:
            self.get_logger().error(f'gimbal_callback failed: {exc}')

    def _maybe_log(self) -> None:
        """按设定间隔输出一次调试日志，避免刷屏。"""
        now = self.get_clock().now()
        elapsed = (now - self.last_log_time).nanoseconds / 1e9
        if elapsed < self.log_interval_sec:
            return
        self.last_log_time = now
        self.get_logger().info(
            'mock_serial_bridge | cmd_vel=[%.3f, %.3f, %.3f] gimbal=[%.2f, %.2f]' % (
                self.latest_cmd_vel[0],
                self.latest_cmd_vel[1],
                self.latest_cmd_vel[2],
                self.latest_gimbal[0],
                self.latest_gimbal[1],
            )
        )


def main(args: Optional[list] = None) -> None:
    """节点入口函数。"""
    rclpy.init(args=args)
    node = MockSerialBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()