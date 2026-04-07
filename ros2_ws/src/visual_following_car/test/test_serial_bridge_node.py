"""serial_bridge_node.py 的单元测试。

测试目标：
1. 验证新协议 V2 打包时，Pan 按“整数度”编码。
2. 验证旧协议 V1 打包时，Pan 按“0.01 度”编码。
3. 验证 CRC 字段计算结果正确。

这些测试不依赖真实串口设备，会用一个 DummySerial 替代 pyserial 的串口对象。
"""

from __future__ import annotations

import struct

import pytest
pytest.importorskip('rclpy')

import visual_following_car.serial_bridge_node as serial_bridge_module
from visual_following_car.serial_bridge_node import COMMAND_FLAG_PROTOCOL_V2, SerialBridgeNode, crc16_ccitt


class DummySerial:
    """一个最小可用的串口替身对象。

    作用：
    - 让 `SerialBridgeNode` 可以正常构造。
    - 记录写入的数据，便于后续断言。
    """

    def __init__(self, *args, **kwargs) -> None:
        self.is_open = True
        self.written = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def close(self) -> None:
        self.is_open = False



def test_build_frame_v2_should_encode_pan_as_integer_degree(monkeypatch, ros_context) -> None:
    """新协议 V2 应把 Pan 角直接编码为整数度。"""
    monkeypatch.setattr(serial_bridge_module.serial, 'Serial', DummySerial)
    node = SerialBridgeNode()
    try:
        node.use_legacy_protocol = False
        frame = node._build_frame(
            sequence=1,
            flags=COMMAND_FLAG_PROTOCOL_V2,
            vx_mps=0.10,
            vy_mps=-0.20,
            omega_radps=0.30,
            pan_angle_deg=123.4,
        )

        assert len(frame) == 16

        encoded_pan = struct.unpack('<h', frame[10:12])[0]
        assert encoded_pan == 123

        expected_crc = crc16_ccitt(frame[:14])
        actual_crc = struct.unpack('<H', frame[14:16])[0]
        assert actual_crc == expected_crc
    finally:
        node.destroy_node()


def test_build_frame_legacy_should_encode_pan_as_centidegree(monkeypatch, ros_context) -> None:
    """旧协议 V1 应把 Pan 角编码为 0.01 度单位。"""
    monkeypatch.setattr(serial_bridge_module.serial, 'Serial', DummySerial)
    node = SerialBridgeNode()
    try:
        node.use_legacy_protocol = True
        frame = node._build_frame(
            sequence=2,
            flags=0,
            vx_mps=0.0,
            vy_mps=0.0,
            omega_radps=0.0,
            pan_angle_deg=120.0,
        )

        assert len(frame) == 16

        encoded_pan = struct.unpack('<h', frame[10:12])[0]
        assert encoded_pan == 12000

        expected_crc = crc16_ccitt(frame[:14])
        actual_crc = struct.unpack('<H', frame[14:16])[0]
        assert actual_crc == expected_crc
    finally:
        node.destroy_node()
