"""visual_follower_node.py 的单元测试。

测试目标：
1. 验证目标偏左/偏右时，Pan 输出会朝正确方向变化。
2. 验证目标丢失或急停时，底盘速度会回到安全状态。
3. 验证禁用云台时，Pan 会回中。

这些测试使用真实 `VisualFollowerNode` 实例，但不依赖真实摄像头或串口硬件。
"""

from __future__ import annotations

import time

import pytest
pytest.importorskip('rclpy')

from std_msgs.msg import Bool, Float32MultiArray

from visual_following_car.visual_follower_node import VisualFollowerNode



def _make_target(center_x: float, distance_m: float = 1.5) -> Float32MultiArray:
    """构造一条模拟的目标检测消息。

    数据布局与正式运行时保持一致：
    `[cx, cy, w, h, confidence, area, distance, image_w, image_h]`
    """
    msg = Float32MultiArray()
    msg.data = [center_x, 0.5, 0.2, 0.4, 0.95, 0.08, distance_m, 640.0, 480.0]
    return msg


def test_target_on_left_should_increase_pan_angle_and_positive_strafe(ros_context) -> None:
    """目标偏左时，Pan 应向一侧偏转，底盘横移量应为正。"""
    node = VisualFollowerNode()
    try:
        node.auto_mode = True
        node.target_callback(_make_target(center_x=0.25, distance_m=1.5))

        # 稍作等待，让 dt 大于 0，避免控制周期近似为零。
        time.sleep(0.05)
        node.timer_callback()

        assert node.pan_deg > node.gimbal_pan_neutral
        assert node.current_cmd.linear.y > 0.0
    finally:
        node.destroy_node()


def test_gimbal_disable_should_force_pan_back_to_neutral(ros_context) -> None:
    """禁用云台时，Pan 角应立即回到中位。"""
    node = VisualFollowerNode()
    try:
        node.pan_deg = 140.0
        msg = Bool()
        msg.data = False
        node.gimbal_enable_callback(msg)
        assert node.pan_deg == node.gimbal_pan_neutral
    finally:
        node.destroy_node()


def test_estop_should_zero_current_command(ros_context) -> None:
    """急停状态下，底盘速度应强制清零。"""
    node = VisualFollowerNode()
    try:
        node.auto_mode = True
        node.target_callback(_make_target(center_x=0.75, distance_m=2.0))
        time.sleep(0.05)

        estop_msg = Bool()
        estop_msg.data = True
        node.estop_callback(estop_msg)
        node.timer_callback()

        assert node.current_cmd.linear.x == 0.0
        assert node.current_cmd.linear.y == 0.0
        assert node.current_cmd.angular.z == 0.0
    finally:
        node.destroy_node()
