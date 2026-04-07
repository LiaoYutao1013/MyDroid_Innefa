"""共享工具函数与数据结构。

这个文件不直接启动 ROS 节点，而是为多个节点提供复用能力：
1. 常用数学辅助函数，例如限幅、死区处理、斜率限制。
2. Pan 云台命令的轻量数据结构封装。
3. PID 控制器封装，便于需要时复用。

把这些公共逻辑集中在一个文件里，可以避免每个节点重复实现相同功能，
也更方便后续统一调参和维护。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


def clamp(value: float, minimum: float, maximum: float) -> float:
    """将数值限制在给定范围内。

    参数说明：
    - value: 待限制的原始值。
    - minimum: 允许的最小值。
    - maximum: 允许的最大值。

    返回值：
    - 返回被限制后的安全值。

    使用场景：
    - 对底盘速度限幅。
    - 对云台角度限位。
    - 对 PID 输出进行裁剪。
    """
    return max(minimum, min(maximum, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    """对摇杆输入应用死区，并把剩余量程重新映射到 -1~1。

    参数说明：
    - value: 摇杆原始输入，通常范围为 -1.0 到 1.0。
    - deadzone: 死区大小，绝对值小于该阈值的输入会被视为 0。

    返回值：
    - 若输入落在死区内，返回 0.0。
    - 若输入超出死区，则按剩余量程重新缩放，确保满量程仍对应 1.0。

    为什么需要这个函数：
    - 手柄摇杆在回中位时常常会有轻微抖动。
    - 不做死区处理会导致底盘或云台在静止时仍出现微小动作。
    """
    if abs(value) <= deadzone:
        return 0.0
    scaled = (abs(value) - deadzone) / max(1.0 - deadzone, 1e-6)
    return scaled if value > 0.0 else -scaled


def slew_limit(target: float, current: float, max_delta: float) -> float:
    """限制相邻控制周期之间的最大变化量，避免输出突变。

    参数说明：
    - target: 本周期希望达到的目标值。
    - current: 当前已经输出的值。
    - max_delta: 单个控制周期内允许变化的最大幅度。

    返回值：
    - 返回一个更平滑的过渡值，而不是直接跳到 target。

    典型用途：
    - 限制底盘速度变化，避免电机突加速。
    - 限制云台回中速度，避免舵机猛甩。
    """
    delta = target - current
    if delta > max_delta:
        return current + max_delta
    if delta < -max_delta:
        return current - max_delta
    return target


@dataclass
class GimbalCommand:
    """Pan-only 云台命令辅助类。

    字段说明：
    - pan_deg: Pan 角度，单位为度。
    - enabled: 当前云台是否允许输出有效角度。

    设计目的：
    - 在多个节点之间传递 Pan 命令时，统一处理“中位回正”和“角度限位”。
    - 保持和旧版 [pan, tilt] 数组格式兼容。
    """

    pan_deg: float
    enabled: bool = True

    @classmethod
    def from_array(
        cls,
        data: List[float],
        neutral_deg: float,
        enabled: bool = True,
    ) -> 'GimbalCommand':
        """从 Float64MultiArray 的 data 中提取 pan 命令。

        参数说明：
        - data: 来自 ROS 话题的数组数据，默认约定第一个元素为 pan。
        - neutral_deg: 当数组为空时使用的默认中位角度。
        - enabled: 外部传入的使能状态。

        返回值：
        - 返回一个 GimbalCommand 对象，方便继续做限位和格式转换。
        """
        if len(data) >= 1:
            return cls(pan_deg=float(data[0]), enabled=enabled)
        return cls(pan_deg=neutral_deg, enabled=enabled)

    def clamped(
        self,
        neutral_deg: float,
        minimum_deg: float,
        maximum_deg: float,
    ) -> 'GimbalCommand':
        """按使能状态和限位范围输出安全的 pan 命令。

        逻辑说明：
        - 如果当前未使能，则强制返回中位角度。
        - 如果当前已使能，则把角度裁剪到安全范围内。

        参数说明：
        - neutral_deg: 未使能时的回中角度。
        - minimum_deg: 允许的最小角度。
        - maximum_deg: 允许的最大角度。
        """
        if not self.enabled:
            return GimbalCommand(pan_deg=neutral_deg, enabled=False)
        return GimbalCommand(
            pan_deg=clamp(self.pan_deg, minimum_deg, maximum_deg),
            enabled=True,
        )

    def to_array(self, neutral_deg: float, minimum_deg: float, maximum_deg: float) -> List[float]:
        """转换为 Float64MultiArray 所需数组格式。

        返回格式说明：
        - 第一个元素为 pan 角度。
        - 第二个元素保留为 0.0。

        之所以保留第二个元素，是为了兼容旧版 [pan, tilt] 布局，
        这样旧代码中订阅/转发数组时不需要大规模重构。
        """
        safe_command = self.clamped(neutral_deg, minimum_deg, maximum_deg)
        return [safe_command.pan_deg, 0.0]


@dataclass
class PidController:
    """小型 PID 控制器，保留给已有逻辑复用。

    字段说明：
    - kp / ki / kd: 比例、积分、微分增益。
    - integral_min / integral_max: 积分项限幅，防止积分饱和。
    - output_min / output_max: 输出限幅。
    - integral: 当前积分累计值。
    - prev_error: 上一个周期的误差值，用于计算微分项。
    """

    kp: float
    ki: float
    kd: float
    integral_min: float
    integral_max: float
    output_min: float
    output_max: float
    integral: float = 0.0
    prev_error: Optional[float] = None

    def reset(self) -> None:
        """清空 PID 内部状态。

        典型场景：
        - 目标丢失。
        - 切换控制模式。
        - 进入急停状态。
        """
        self.integral = 0.0
        self.prev_error = None

    def step(self, error: float, dt: float) -> float:
        """执行一次 PID 计算并返回控制输出。

        参数说明：
        - error: 当前误差。
        - dt: 距离上一次控制计算经过的时间，单位秒。

        返回值：
        - 经过积分限幅和输出限幅后的控制量。
        """
        if dt <= 0.0:
            proportional = self.kp * error
            return clamp(proportional, self.output_min, self.output_max)

        self.integral += error * dt
        self.integral = clamp(self.integral, self.integral_min, self.integral_max)

        derivative = 0.0
        if self.prev_error is not None:
            derivative = (error - self.prev_error) / dt

        self.prev_error = error
        output = (
            (self.kp * error)
            + (self.ki * self.integral)
            + (self.kd * derivative)
        )
        return clamp(output, self.output_min, self.output_max)