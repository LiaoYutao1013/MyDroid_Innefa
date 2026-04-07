#include "motor_control.h"
#include "app_config.h"

#include <math.h>
#include <stddef.h>

/*
 * motor_control.c
 *
 * 这个文件实现两类执行层控制：
 * 1. 4 个麦轮电机的开环 PWM 控制。
 * 2. Pan 云台舵机的角度控制。
 *
 * 设计思想：
 * - 上层只给出车体速度（vx, vy, omega）和云台角度。
 * - 本文件负责把这些“抽象控制量”映射成 GPIO + PWM 的具体动作。
 */

typedef struct
{
    GPIO_TypeDef *in1_port;
    uint16_t in1_pin;
    GPIO_TypeDef *in2_port;
    uint16_t in2_pin;
    uint32_t pwm_channel;
    uint8_t reversed;
} MotorChannel;

/* 底盘电机 PWM 定时器句柄。 */
static TIM_HandleTypeDef *s_motor_tim = NULL;

/* Pan 舵机 PWM 定时器句柄。 */
static TIM_HandleTypeDef *s_pan_servo_tim = NULL;

/*
 * 4 个电机的硬件映射表。
 * 顺序约定：
 * 0 -> 前左轮
 * 1 -> 前右轮
 * 2 -> 后左轮
 * 3 -> 后右轮
 */
static const MotorChannel s_motor_channels[4] =
{
    {FL_IN1_GPIO_Port, FL_IN1_Pin, FL_IN2_GPIO_Port, FL_IN2_Pin, TIM_CHANNEL_1, FRONT_LEFT_MOTOR_REVERSED},
    {FR_IN1_GPIO_Port, FR_IN1_Pin, FR_IN2_GPIO_Port, FR_IN2_Pin, TIM_CHANNEL_2, FRONT_RIGHT_MOTOR_REVERSED},
    {RL_IN1_GPIO_Port, RL_IN1_Pin, RL_IN2_GPIO_Port, RL_IN2_Pin, TIM_CHANNEL_3, REAR_LEFT_MOTOR_REVERSED},
    {RR_IN1_GPIO_Port, RR_IN1_Pin, RR_IN2_GPIO_Port, RR_IN2_Pin, TIM_CHANNEL_4, REAR_RIGHT_MOTOR_REVERSED},
};

/* 浮点数限幅工具函数。 */
static float MotorControl_ClampFloat(float value, float minimum, float maximum)
{
    if (value < minimum)
    {
        return minimum;
    }
    if (value > maximum)
    {
        return maximum;
    }
    return value;
}

/* Pan 角度限位函数。 */
static int16_t MotorControl_ClampPanAngle(int16_t angle_deg)
{
    if (angle_deg < PAN_SERVO_MIN_DEG)
    {
        return PAN_SERVO_MIN_DEG;
    }
    if (angle_deg > PAN_SERVO_MAX_DEG)
    {
        return PAN_SERVO_MAX_DEG;
    }
    return angle_deg;
}

/*
 * 把目标角度映射为舵机 PWM 脉宽。
 *
 * 映射规则：
 * - 最小角度 -> 最小脉宽
 * - 最大角度 -> 最大脉宽
 * - 中间角度按线性比例插值
 */
static uint32_t MotorControl_PanPulseFromAngle(int16_t angle_deg)
{
    const int16_t clamped_angle_deg = MotorControl_ClampPanAngle(angle_deg);
    float mapped_angle_deg = (float)clamped_angle_deg;

    /*
     * 如果物理安装方向和逻辑方向相反，
     * 可以通过 PAN_SERVO_REVERSED 宏反转映射方向。
     */
    if (PAN_SERVO_REVERSED != 0U)
    {
        mapped_angle_deg = (float)PAN_SERVO_MAX_DEG - (mapped_angle_deg - (float)PAN_SERVO_MIN_DEG);
    }

    const float angle_span_deg = (float)(PAN_SERVO_MAX_DEG - PAN_SERVO_MIN_DEG);
    const float ratio = (angle_span_deg > 0.001f)
        ? ((mapped_angle_deg - (float)PAN_SERVO_MIN_DEG) / angle_span_deg)
        : 0.5f;
    const float pulse_span_us = (float)(PAN_SERVO_MAX_PULSE_US - PAN_SERVO_MIN_PULSE_US);

    return (uint32_t)((float)PAN_SERVO_MIN_PULSE_US + (ratio * pulse_span_us));
}

/*
 * 设置某个轮子的归一化速度。
 *
 * 参数说明：
 * - index: 电机索引，0~3。
 * - normalized: 归一化速度，范围 -1.0~1.0。
 *
 * 逻辑说明：
 * - 正值表示正转，负值表示反转。
 * - 绝对值决定 PWM 占空比。
 * - 如果值过小，则直接停车，避免抖动。
 */
static void MotorControl_SetMotorNormalized(uint8_t index, float normalized)
{
    if ((s_motor_tim == NULL) || (index >= 4U))
    {
        return;
    }

    const MotorChannel *motor = &s_motor_channels[index];
    normalized = MotorControl_ClampFloat(normalized, -1.0f, 1.0f);
    if (motor->reversed != 0U)
    {
        normalized = -normalized;
    }

    if (fabsf(normalized) < MOTOR_ZERO_DEADBAND)
    {
        HAL_GPIO_WritePin(motor->in1_port, motor->in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(motor->in2_port, motor->in2_pin, GPIO_PIN_RESET);
        __HAL_TIM_SET_COMPARE(s_motor_tim, motor->pwm_channel, 0U);
        return;
    }

    if (normalized >= 0.0f)
    {
        HAL_GPIO_WritePin(motor->in1_port, motor->in1_pin, GPIO_PIN_SET);
        HAL_GPIO_WritePin(motor->in2_port, motor->in2_pin, GPIO_PIN_RESET);
    }
    else
    {
        HAL_GPIO_WritePin(motor->in1_port, motor->in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(motor->in2_port, motor->in2_pin, GPIO_PIN_SET);
    }

    uint32_t duty_counts = (uint32_t)(fabsf(normalized) * (float)MOTOR_PWM_PERIOD_COUNTS);
    if ((duty_counts > 0U) && (duty_counts < MOTOR_PWM_MIN_EFFECTIVE_COUNTS))
    {
        duty_counts = MOTOR_PWM_MIN_EFFECTIVE_COUNTS;
    }
    if (duty_counts > MOTOR_PWM_PERIOD_COUNTS)
    {
        duty_counts = MOTOR_PWM_PERIOD_COUNTS;
    }

    __HAL_TIM_SET_COMPARE(s_motor_tim, motor->pwm_channel, duty_counts);
}

void MotorControl_Init(TIM_HandleTypeDef *motor_tim, TIM_HandleTypeDef *pan_servo_tim)
{
    s_motor_tim = motor_tim;
    s_pan_servo_tim = pan_servo_tim;

    /* 启动 4 路底盘电机 PWM。 */
    HAL_TIM_PWM_Start(s_motor_tim, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(s_motor_tim, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(s_motor_tim, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(s_motor_tim, TIM_CHANNEL_4);

    /* 启动 Pan 云台 PWM。 */
    HAL_TIM_PWM_Start(s_pan_servo_tim, PAN_SERVO_CHANNEL);

    MotorControl_SetDriverEnabled(true);
    MotorControl_StopAll();
    gimbal_pan_control(PAN_SERVO_NEUTRAL_DEG);
}

void MotorControl_SetDriverEnabled(bool enabled)
{
    HAL_GPIO_WritePin(MOTOR_STBY_GPIO_Port, MOTOR_STBY_Pin, enabled ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

void MotorControl_StopAll(void)
{
    uint8_t index;
    for (index = 0U; index < 4U; ++index)
    {
        MotorControl_SetMotorNormalized(index, 0.0f);
    }
}

void MotorControl_SetBodyVelocity(float vx_mps, float vy_mps, float omega_radps)
{
    /*
     * 第一步：先对输入的车体速度做限幅，防止超出系统允许范围。
     */
    vx_mps = MotorControl_ClampFloat(vx_mps, -MAX_BODY_VX_MPS, MAX_BODY_VX_MPS);
    vy_mps = MotorControl_ClampFloat(vy_mps, -MAX_BODY_VY_MPS, MAX_BODY_VY_MPS);
    omega_radps = MotorControl_ClampFloat(omega_radps, -MAX_BODY_OMEGA_RADPS, MAX_BODY_OMEGA_RADPS);

    /*
     * 第二步：使用标准麦轮逆运动学公式，把车体速度转换成各轮角速度。
     *
     * 坐标系约定：
     * - x 正方向：车头朝前
     * - y 正方向：车体左侧
     * - z 正方向：竖直向上
     * - omega > 0：逆时针旋转
     *
     * 公式如下：
     * w_fl = (vx - vy - (L + W) * omega) / R
     * w_fr = (vx + vy + (L + W) * omega) / R
     * w_rl = (vx + vy - (L + W) * omega) / R
     * w_rr = (vx - vy + (L + W) * omega) / R
     *
     * 其中：
     * - L: 半长度
     * - W: 半宽度
     * - R: 轮子半径
     */
    const float k = CHASSIS_HALF_LENGTH_M + CHASSIS_HALF_WIDTH_M;
    float wheel_fl = (vx_mps - vy_mps - (k * omega_radps)) / WHEEL_RADIUS_M;
    float wheel_fr = (vx_mps + vy_mps + (k * omega_radps)) / WHEEL_RADIUS_M;
    float wheel_rl = (vx_mps + vy_mps - (k * omega_radps)) / WHEEL_RADIUS_M;
    float wheel_rr = (vx_mps - vy_mps + (k * omega_radps)) / WHEEL_RADIUS_M;

    /*
     * 第三步：把轮速归一化到 -1~1。
     * 这里使用估计的最大轮角速度来映射到 PWM 占空比。
     */
    float norm_fl = wheel_fl / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_fr = wheel_fr / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_rl = wheel_rl / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_rr = wheel_rr / MAX_WHEEL_ANGULAR_SPEED_RADPS;

    /*
     * 第四步：如果任何一个轮子的绝对值超过 1，则对四个轮子一起按比例缩放。
     * 这样可以保持速度方向关系不变。
     */
    float max_mag = fabsf(norm_fl);
    if (fabsf(norm_fr) > max_mag) { max_mag = fabsf(norm_fr); }
    if (fabsf(norm_rl) > max_mag) { max_mag = fabsf(norm_rl); }
    if (fabsf(norm_rr) > max_mag) { max_mag = fabsf(norm_rr); }

    if (max_mag > 1.0f)
    {
        norm_fl /= max_mag;
        norm_fr /= max_mag;
        norm_rl /= max_mag;
        norm_rr /= max_mag;
    }

    /* 最后一步：把归一化结果分别输出到 4 个轮子。 */
    MotorControl_SetMotorNormalized(0U, norm_fl);
    MotorControl_SetMotorNormalized(1U, norm_fr);
    MotorControl_SetMotorNormalized(2U, norm_rl);
    MotorControl_SetMotorNormalized(3U, norm_rr);
}

void gimbal_pan_control(int16_t pan_angle_deg)
{
    if ((s_pan_servo_tim == NULL) || (s_pan_servo_tim->Instance != PAN_SERVO_TIM))
    {
        return;
    }

    /*
     * Pan 云台控制步骤：
     * 1. 限制目标角度在安全范围内。
     * 2. 将角度线性映射到舵机脉宽。
     * 3. 把脉宽写入指定定时器通道的比较寄存器。
     */
    const uint32_t pulse_us = MotorControl_PanPulseFromAngle(pan_angle_deg);
    __HAL_TIM_SET_COMPARE(s_pan_servo_tim, PAN_SERVO_CHANNEL, pulse_us);
}

void MotorControl_ApplyCommand(const RobotCommand *command)
{
    if (command == NULL)
    {
        return;
    }

    /* 先处理云台，即使底盘停车，也允许云台保持当前角度。 */
    gimbal_pan_control(command->pan_angle_deg);

    if ((!command->command_valid) || command->estop)
    {
        MotorControl_StopAll();
        return;
    }

    MotorControl_SetBodyVelocity(command->vx_mps, command->vy_mps, command->omega_radps);
}