"""common.py 的单元测试。

测试目标：
1. 验证常用数学辅助函数行为正确。
2. 验证 GimbalCommand 的限位和数组转换逻辑。
3. 验证 PidController 的基本输出行为。

这些测试不依赖 ROS2 运行时，适合作为最快的一层回归测试。
"""

from __future__ import annotations

from visual_following_car.common import GimbalCommand, PidController, apply_deadzone, clamp, slew_limit


def test_clamp_should_limit_value_into_range() -> None:
    """`clamp()` 应当把输入值限制在最小值和最大值之间。"""
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-1.0, 0.0, 10.0) == 0.0
    assert clamp(99.0, 0.0, 10.0) == 10.0


def test_apply_deadzone_should_zero_small_input_and_scale_large_input() -> None:
    """`apply_deadzone()` 应当抑制小抖动，并保留大幅摇杆输入。"""
    assert apply_deadzone(0.05, 0.10) == 0.0
    assert apply_deadzone(-0.05, 0.10) == 0.0

    # 超出死区后应保留方向，且绝对值仍在 0~1 之间。
    positive = apply_deadzone(0.50, 0.10)
    negative = apply_deadzone(-0.50, 0.10)
    assert 0.0 < positive <= 1.0
    assert -1.0 <= negative < 0.0


def test_slew_limit_should_only_allow_small_step_change() -> None:
    """`slew_limit()` 应当限制相邻周期的最大变化量。"""
    assert slew_limit(10.0, 0.0, 2.0) == 2.0
    assert slew_limit(-10.0, 0.0, 2.0) == -2.0
    assert slew_limit(1.0, 0.0, 2.0) == 1.0


def test_gimbal_command_should_return_neutral_when_disabled() -> None:
    """云台禁用时，无论输入角度是多少，都应回到中位。"""
    command = GimbalCommand(pan_deg=150.0, enabled=False)
    safe = command.clamped(neutral_deg=90.0, minimum_deg=0.0, maximum_deg=160.0)
    assert safe.pan_deg == 90.0
    assert safe.enabled is False


def test_gimbal_command_to_array_should_keep_legacy_two_element_layout() -> None:
    """数组输出应保留 `[pan, 0.0]` 布局，以兼容旧接口。"""
    command = GimbalCommand(pan_deg=120.0, enabled=True)
    assert command.to_array(90.0, 0.0, 160.0) == [120.0, 0.0]


def test_pid_controller_should_generate_positive_output_for_positive_error() -> None:
    """PID 控制器面对正误差时，输出应朝正方向变化。"""
    controller = PidController(
        kp=2.0,
        ki=0.0,
        kd=0.0,
        integral_min=-1.0,
        integral_max=1.0,
        output_min=-10.0,
        output_max=10.0,
    )
    output = controller.step(0.5, 0.1)
    assert output > 0.0