#!/usr/bin/env python3
"""串口桥接节点。

文件职责：
1. 接收上层 ROS2 节点产生的底盘速度与云台角度命令。
2. 根据当前模式（手动 / 自动）选择有效命令源。
3. 对命令进行超时检查、急停检查和限幅。
4. 按既定协议打包为固定长度的 UART 帧，发送给 STM32。

兼容性说明：
- 支持旧协议（Pan 用 0.01 度单位表示）。
- 支持新协议（Pan 用 int16 的整数度表示）。
- 通过 `use_legacy_protocol` 参数切换。
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Optional

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, Float64MultiArray

from .common import GimbalCommand, clamp

if TYPE_CHECKING:
    import serial

try:
    import serial
    from serial import SerialException
except ImportError as exc:  # pragma: no cover
    serial = None
    SerialException = Exception
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

# 协议标志位定义：这些位会被打包到一帧中的 flags 字节里。
COMMAND_FLAG_AUTO = 0x01
COMMAND_FLAG_ESTOP = 0x02
COMMAND_FLAG_VALID = 0x04
COMMAND_FLAG_PROTOCOL_V2 = 0x08


def crc16_ccitt(data: bytes) -> int:
    """计算 CRC16-CCITT。

    参数说明：
    - data: 需要做校验的字节序列。

    返回值：
    - 16 位 CRC 校验值。

    为什么需要 CRC：
    - UART 在实际布线中可能会出现干扰。
    - STM32 通过 CRC 可以丢弃损坏帧，避免误动作。
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class SerialBridgeNode(Node):
    """选择手动/自动控制源，并向 STM32 发送协议帧。"""

    def __init__(self) -> None:
        """初始化串口参数、订阅器、状态变量和定时发送器。"""
        super().__init__('serial_bridge_node')

        if serial is None:
            raise RuntimeError('pyserial is not installed.') from IMPORT_ERROR

        # 串口桥必须声明所有可调参数，便于通过 YAML 配置不同硬件。
        self.declare_parameters(
            namespace='',
            parameters=[
                ('port', '/dev/ttyS1'),
                ('baudrate', 115200),
                ('send_rate_hz', 30.0),
                ('command_timeout_sec', 0.5),
                ('reconnect_interval_sec', 2.0),
                ('use_legacy_protocol', False),
                ('max_linear_x_mps', 0.8),
                ('max_linear_y_mps', 0.6),
                ('max_angular_z_radps', 1.2),
                ('pan_min_deg', 0.0),
                ('pan_max_deg', 180.0),
                ('gimbal.pan_enabled', True),
                ('gimbal.pan_neutral', 90.0),
                ('gimbal.pan_max_angle', 160.0),
            ],
        )

        # 读取串口和控制边界参数。
        self.port = str(self.get_parameter('port').value)
        self.baudrate = int(self.get_parameter('baudrate').value)
        self.send_rate_hz = float(self.get_parameter('send_rate_hz').value)
        self.command_timeout_sec = float(self.get_parameter('command_timeout_sec').value)
        self.reconnect_interval_sec = float(self.get_parameter('reconnect_interval_sec').value)
        self.use_legacy_protocol = bool(self.get_parameter('use_legacy_protocol').value)
        self.max_linear_x_mps = float(self.get_parameter('max_linear_x_mps').value)
        self.max_linear_y_mps = float(self.get_parameter('max_linear_y_mps').value)
        self.max_angular_z_radps = float(self.get_parameter('max_angular_z_radps').value)
        self.pan_min_deg = float(self.get_parameter('pan_min_deg').value)
        self.pan_max_deg = min(
            float(self.get_parameter('pan_max_deg').value),
            float(self.get_parameter('gimbal.pan_max_angle').value),
        )
        self.gimbal_pan_enabled = bool(self.get_parameter('gimbal.pan_enabled').value)
        self.gimbal_pan_neutral = float(self.get_parameter('gimbal.pan_neutral').value)

        # 全局运行状态。
        self.auto_mode = False
        self.estop_active = False
        self.sequence = 0
        self.serial_port: Optional['serial.Serial'] = None
        self.last_reconnect_attempt = self.get_clock().now()

        # 为手动和自动两套控制源分别缓存最新命令。
        self.teleop_cmd = Twist()
        self.auto_cmd = Twist()
        self.teleop_gimbal = [self.gimbal_pan_neutral, 0.0]
        self.auto_gimbal = [self.gimbal_pan_neutral, 0.0]
        now = self.get_clock().now()
        self.teleop_cmd_time = now
        self.auto_cmd_time = now
        self.teleop_gimbal_time = now
        self.auto_gimbal_time = now

        # 订阅多个话题，让本节点成为“控制量汇聚器”。
        self.teleop_cmd_sub = self.create_subscription(Twist, 'teleop/cmd_vel', self.teleop_cmd_callback, 10)
        self.auto_cmd_sub = self.create_subscription(Twist, 'auto/cmd_vel', self.auto_cmd_callback, 10)
        self.teleop_gimbal_sub = self.create_subscription(Float64MultiArray, 'teleop/gimbal_cmd', self.teleop_gimbal_callback, 10)
        self.auto_gimbal_sub = self.create_subscription(Float64MultiArray, 'auto/gimbal_cmd', self.auto_gimbal_callback, 10)
        self.auto_mode_sub = self.create_subscription(Bool, 'auto_mode', self.auto_mode_callback, 10)
        self.estop_sub = self.create_subscription(Bool, 'emergency_stop', self.estop_callback, 10)
        self.gimbal_enable_sub = self.create_subscription(Bool, 'gimbal_pan_enabled', self.gimbal_enable_callback, 10)

        # 打开串口；如果此时失败，后续 timer 会自动尝试重连。
        self._open_serial()
        timer_period = 1.0 / max(self.send_rate_hz, 1.0)
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'Serial bridge ready: port={self.port} baud={self.baudrate} '
            f'legacy={self.use_legacy_protocol} pan_enabled={self.gimbal_pan_enabled} '
            f'pan_neutral={self.gimbal_pan_neutral:.1f} pan_max={self.pan_max_deg:.1f}'
        )

    def _open_serial(self) -> None:
        """尝试打开串口设备。

        如果串口不存在、权限不足或已被占用，本函数不会让节点崩溃，
        而是记录告警并等待后续定时器再次尝试重连。
        """
        try:
            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.0,
                write_timeout=0.05,
            )
            self.get_logger().info(f'Opened serial port {self.port} @ {self.baudrate}')
        except SerialException as exc:
            self.serial_port = None
            self.get_logger().warning(f'Unable to open serial port {self.port}: {exc}')

    def teleop_cmd_callback(self, msg: Twist) -> None:
        """缓存手动底盘速度命令。"""
        try:
            self.teleop_cmd = msg
            self.teleop_cmd_time = self.get_clock().now()
        except Exception as exc:
            self.get_logger().error(f'teleop_cmd_callback failed: {exc}')

    def auto_cmd_callback(self, msg: Twist) -> None:
        """缓存自动跟随产生的底盘速度命令。"""
        try:
            self.auto_cmd = msg
            self.auto_cmd_time = self.get_clock().now()
        except Exception as exc:
            self.get_logger().error(f'auto_cmd_callback failed: {exc}')

    def teleop_gimbal_callback(self, msg: Float64MultiArray) -> None:
        """缓存手动云台角度命令。"""
        try:
            if len(msg.data) >= 1:
                self.teleop_gimbal = list(msg.data)
                self.teleop_gimbal_time = self.get_clock().now()
        except Exception as exc:
            self.get_logger().error(f'teleop_gimbal_callback failed: {exc}')

    def auto_gimbal_callback(self, msg: Float64MultiArray) -> None:
        """缓存自动跟随产生的云台角度命令。"""
        try:
            if len(msg.data) >= 1:
                self.auto_gimbal = list(msg.data)
                self.auto_gimbal_time = self.get_clock().now()
        except Exception as exc:
            self.get_logger().error(f'auto_gimbal_callback failed: {exc}')

    def auto_mode_callback(self, msg: Bool) -> None:
        """更新当前是否处于自动跟随模式。"""
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
        """更新云台使能状态。"""
        try:
            self.gimbal_pan_enabled = bool(msg.data)
        except Exception as exc:
            self.get_logger().error(f'gimbal_enable_callback failed: {exc}')

    def timer_callback(self) -> None:
        """按固定频率挑选有效命令并发送串口帧。

        核心流程：
        1. 若串口未打开，则按重连周期重试。
        2. 根据当前模式，从手动或自动缓存里选择命令。
        3. 检查命令是否超时、是否急停。
        4. 对底盘速度和云台角度做限幅。
        5. 打包为 UART 二进制帧并发送。
        """
        try:
            now = self.get_clock().now()
            if self.serial_port is None or not self.serial_port.is_open:
                if (now - self.last_reconnect_attempt).nanoseconds / 1e9 >= self.reconnect_interval_sec:
                    self.last_reconnect_attempt = now
                    self._open_serial()
                return

            if self.auto_mode:
                cmd = self.auto_cmd
                cmd_time = self.auto_cmd_time
                gimbal_array = self.auto_gimbal
                gimbal_time = self.auto_gimbal_time
            else:
                cmd = self.teleop_cmd
                cmd_time = self.teleop_cmd_time
                gimbal_array = self.teleop_gimbal
                gimbal_time = self.teleop_gimbal_time

            # 底盘速度和云台角度都必须在有效超时范围内，否则视为无效命令。
            cmd_fresh = ((now - cmd_time).nanoseconds / 1e9) <= self.command_timeout_sec
            if self.gimbal_pan_enabled:
                gimbal_fresh = ((now - gimbal_time).nanoseconds / 1e9) <= self.command_timeout_sec
            else:
                gimbal_fresh = True
            command_valid = cmd_fresh and gimbal_fresh

            # 任何无效命令或急停状态下，都强制发送零速度。
            if not command_valid or self.estop_active:
                vx = 0.0
                vy = 0.0
                omega = 0.0
            else:
                vx = clamp(float(cmd.linear.x), -self.max_linear_x_mps, self.max_linear_x_mps)
                vy = clamp(float(cmd.linear.y), -self.max_linear_y_mps, self.max_linear_y_mps)
                omega = clamp(float(cmd.angular.z), -self.max_angular_z_radps, self.max_angular_z_radps)

            # 云台命令的使能与限位统一交给 GimbalCommand 处理。
            gimbal_command = GimbalCommand.from_array(
                gimbal_array,
                self.gimbal_pan_neutral,
                enabled=self.gimbal_pan_enabled,
            ).clamped(self.gimbal_pan_neutral, self.pan_min_deg, self.pan_max_deg)

            # 组装协议标志位。
            flags = 0
            if self.auto_mode:
                flags |= COMMAND_FLAG_AUTO
            if self.estop_active:
                flags |= COMMAND_FLAG_ESTOP
            if command_valid:
                flags |= COMMAND_FLAG_VALID
            if not self.use_legacy_protocol:
                flags |= COMMAND_FLAG_PROTOCOL_V2

            frame = self._build_frame(
                sequence=self.sequence,
                flags=flags,
                vx_mps=vx,
                vy_mps=vy,
                omega_radps=omega,
                pan_angle_deg=gimbal_command.pan_deg,
            )
            self.sequence = (self.sequence + 1) & 0xFF
            self.serial_port.write(frame)
        except SerialException as exc:
            self.get_logger().error(f'Serial write failed: {exc}')
            self._close_serial()
        except Exception as exc:
            self.get_logger().error(f'timer_callback failed: {exc}')

    def _build_frame(
        self,
        sequence: int,
        flags: int,
        vx_mps: float,
        vy_mps: float,
        omega_radps: float,
        pan_angle_deg: float,
    ) -> bytes:
        """构造一帧发给 STM32 的串口协议数据。

        参数说明：
        - sequence: 帧序号，便于调试丢帧和乱序问题。
        - flags: 标志位字节。
        - vx_mps / vy_mps / omega_radps: 底盘控制量。
        - pan_angle_deg: Pan 角度，单位为度。

        单位转换：
        - 线速度从 m/s 转为 mm/s。
        - 角速度从 rad/s 转为 mrad/s。
        - Pan 根据新旧协议决定编码方式。
        """
        vx_mmps = int(round(vx_mps * 1000.0))
        vy_mmps = int(round(vy_mps * 1000.0))
        omega_mradps = int(round(omega_radps * 1000.0))
        pan_angle_deg_int = int(round(clamp(pan_angle_deg, self.pan_min_deg, self.pan_max_deg)))

        if self.use_legacy_protocol:
            # 旧协议要求 pan 使用 0.01 度单位，
            # bytes 12-13 保留旧 tilt 中位值以兼容旧固件。
            payload = struct.pack(
                '<BBBBhhhhH',
                0xAA,
                0x55,
                sequence & 0xFF,
                flags & 0xFF,
                vx_mmps,
                vy_mmps,
                omega_mradps,
                int(round(pan_angle_deg_int * 100)),
                int(round(self.gimbal_pan_neutral * 100)),
            )
        else:
            # 新协议：bytes 10-11 直接发送整数角度，bytes 12-13 保留。
            payload = struct.pack(
                '<BBBBhhhhH',
                0xAA,
                0x55,
                sequence & 0xFF,
                flags & 0xFF,
                vx_mmps,
                vy_mmps,
                omega_mradps,
                pan_angle_deg_int,
                0,
            )

        crc = crc16_ccitt(payload)
        return payload + struct.pack('<H', crc)

    def _close_serial(self) -> None:
        """关闭串口并清空句柄。"""
        if self.serial_port is not None:
            try:
                self.serial_port.close()
            except SerialException:
                pass
        self.serial_port = None
        self.last_reconnect_attempt = self.get_clock().now()

    def destroy_node(self) -> bool:
        """节点销毁前关闭串口资源。"""
        self._close_serial()
        return super().destroy_node()


def main(args: Optional[list] = None) -> None:
    """节点入口函数。"""
    rclpy.init(args=args)
    node = SerialBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()