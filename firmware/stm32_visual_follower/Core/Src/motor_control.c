#include "motor_control.h"
#include "app_config.h"

#include <math.h>
#include <stddef.h>

/*
 * motor_control.c
 *
 * 这次修复的重点，是把电机控制层从“旧版单定时器 4 路 PWM + Pan 舵机”的假设，
 * 改成“当前 CubeMX 实际生成的双定时器 4 路麦轮 PWM”：
 *
 * - 前左轮：TIM1_CH1 / PE9
 * - 前右轮：TIM1_CH4 / PE14
 * - 后左轮：TIM4_CH1 / PD12
 * - 后右轮：TIM4_CH4 / PD15
 *
 * 由于当前阶段只打通麦轮链路，因此：
 * 1. 不再启动任何 Pan/云台 PWM；
 * 2. RobotCommand 里的 pan_angle_deg 仅为协议兼容保留；
 * 3. 所有实际输出都只针对 4 个底盘电机。
 */

typedef struct
{
    TIM_HandleTypeDef *pwm_tim;
    uint32_t pwm_channel;
    GPIO_TypeDef *in1_port;
    uint16_t in1_pin;
    GPIO_TypeDef *in2_port;
    uint16_t in2_pin;
    uint8_t reversed;
} MotorChannel;

/*
 * 轮子顺序约定：
 * 0 -> 前左
 * 1 -> 前右
 * 2 -> 后左
 * 3 -> 后右
 */
static MotorChannel s_motor_channels[4] =
{
    {NULL, TIM_CHANNEL_1, FL_IN1_GPIO_Port, FL_IN1_Pin, FL_IN2_GPIO_Port, FL_IN2_Pin, FRONT_LEFT_MOTOR_REVERSED},
    {NULL, TIM_CHANNEL_4, FR_IN1_GPIO_Port, FR_IN1_Pin, FR_IN2_GPIO_Port, FR_IN2_Pin, FRONT_RIGHT_MOTOR_REVERSED},
    {NULL, TIM_CHANNEL_1, RL_IN1_GPIO_Port, RL_IN1_Pin, RL_IN2_GPIO_Port, RL_IN2_Pin, REAR_LEFT_MOTOR_REVERSED},
    {NULL, TIM_CHANNEL_4, RR_IN1_GPIO_Port, RR_IN1_Pin, RR_IN2_GPIO_Port, RR_IN2_Pin, REAR_RIGHT_MOTOR_REVERSED},
};

static TIM_HandleTypeDef *s_front_pwm_tim = NULL;
static TIM_HandleTypeDef *s_rear_pwm_tim = NULL;

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

static void MotorControl_AssignTimers(TIM_HandleTypeDef *front_pwm_tim, TIM_HandleTypeDef *rear_pwm_tim)
{
    s_front_pwm_tim = front_pwm_tim;
    s_rear_pwm_tim = rear_pwm_tim;

    /*
     * 前轴两轮共用 TIM1，后轴两轮共用 TIM4。
     * 这里把定时器句柄写入每个轮子的映射表，后续设置占空比时就不需要再分支判断。
     */
    s_motor_channels[0].pwm_tim = s_front_pwm_tim;
    s_motor_channels[1].pwm_tim = s_front_pwm_tim;
    s_motor_channels[2].pwm_tim = s_rear_pwm_tim;
    s_motor_channels[3].pwm_tim = s_rear_pwm_tim;
}

static void MotorControl_StartPwmOutputs(void)
{
    if (s_front_pwm_tim != NULL)
    {
        HAL_TIM_PWM_Start(s_front_pwm_tim, TIM_CHANNEL_1);
        HAL_TIM_PWM_Start(s_front_pwm_tim, TIM_CHANNEL_4);
    }

    if (s_rear_pwm_tim != NULL)
    {
        HAL_TIM_PWM_Start(s_rear_pwm_tim, TIM_CHANNEL_1);
        HAL_TIM_PWM_Start(s_rear_pwm_tim, TIM_CHANNEL_4);
    }
}

static void MotorControl_SetMotorDirection(const MotorChannel *motor, float normalized)
{
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
}

static void MotorControl_SetMotorNormalized(uint8_t index, float normalized)
{
    if (index >= 4U)
    {
        return;
    }

    MotorChannel *motor = &s_motor_channels[index];
    if (motor->pwm_tim == NULL)
    {
        return;
    }

    normalized = MotorControl_ClampFloat(normalized, -1.0f, 1.0f);
    if (motor->reversed != 0U)
    {
        normalized = -normalized;
    }

    if (fabsf(normalized) < MOTOR_ZERO_DEADBAND)
    {
        HAL_GPIO_WritePin(motor->in1_port, motor->in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(motor->in2_port, motor->in2_pin, GPIO_PIN_RESET);
        __HAL_TIM_SET_COMPARE(motor->pwm_tim, motor->pwm_channel, 0U);
        return;
    }

    MotorControl_SetMotorDirection(motor, normalized);

    /*
     * 关键点：
     * 当前 4 个电机并不在同一个定时器上，必须读取各自定时器的 ARR 做比例换算，
     * 不能再沿用旧版“所有电机共享同一个 PWM 周期计数”的写法。
     */
    const uint32_t pwm_arr = __HAL_TIM_GET_AUTORELOAD(motor->pwm_tim);
    const float magnitude = fabsf(normalized);
    uint32_t duty_counts = (uint32_t)(magnitude * (float)pwm_arr);
    uint32_t min_effective_counts = (uint32_t)((float)pwm_arr * MOTOR_PWM_MIN_EFFECTIVE_RATIO);

    if ((min_effective_counts == 0U) && (magnitude > 0.0f))
    {
        min_effective_counts = 1U;
    }

    if ((duty_counts > 0U) && (duty_counts < min_effective_counts))
    {
        duty_counts = min_effective_counts;
    }
    if (duty_counts > pwm_arr)
    {
        duty_counts = pwm_arr;
    }

    __HAL_TIM_SET_COMPARE(motor->pwm_tim, motor->pwm_channel, duty_counts);
}

void MotorControl_Init(TIM_HandleTypeDef *front_pwm_tim, TIM_HandleTypeDef *rear_pwm_tim)
{
    MotorControl_AssignTimers(front_pwm_tim, rear_pwm_tim);
    MotorControl_StartPwmOutputs();

    /*
     * 当前这套 CubeMX 映射没有单独预留 STBY/EN 脚给驱动板，
     * 因此这里只保留接口，不做额外硬件操作。
     */
    MotorControl_SetDriverEnabled(true);
    MotorControl_StopAll();
}

void MotorControl_SetDriverEnabled(bool enabled)
{
    (void)enabled;
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
     * 第一步：先对车体速度命令做限幅，确保不会超出当前开环阶段允许的范围。
     */
    vx_mps = MotorControl_ClampFloat(vx_mps, -MAX_BODY_VX_MPS, MAX_BODY_VX_MPS);
    vy_mps = MotorControl_ClampFloat(vy_mps, -MAX_BODY_VY_MPS, MAX_BODY_VY_MPS);
    omega_radps = MotorControl_ClampFloat(omega_radps, -MAX_BODY_OMEGA_RADPS, MAX_BODY_OMEGA_RADPS);

    /*
     * 第二步：麦克纳姆底盘逆运动学。
     * 坐标系约定：
     * - x 正方向：车头向前；
     * - y 正方向：车体左侧；
     * - omega 正方向：车体逆时针旋转。
     */
    const float k = CHASSIS_HALF_LENGTH_M + CHASSIS_HALF_WIDTH_M;
    const float wheel_fl = (vx_mps - vy_mps - (k * omega_radps)) / WHEEL_RADIUS_M;
    const float wheel_fr = (vx_mps + vy_mps + (k * omega_radps)) / WHEEL_RADIUS_M;
    const float wheel_rl = (vx_mps + vy_mps - (k * omega_radps)) / WHEEL_RADIUS_M;
    const float wheel_rr = (vx_mps - vy_mps + (k * omega_radps)) / WHEEL_RADIUS_M;

    /*
     * 第三步：把各轮角速度映射为 -1.0 ~ 1.0 的归一化命令。
     */
    float norm_fl = wheel_fl / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_fr = wheel_fr / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_rl = wheel_rl / MAX_WHEEL_ANGULAR_SPEED_RADPS;
    float norm_rr = wheel_rr / MAX_WHEEL_ANGULAR_SPEED_RADPS;

    /*
     * 第四步：整体归一化。
     * 如果某个轮子的幅值先超过 1.0，则按比例缩放 4 个轮子，
     * 这样能保持目标运动方向不变，只降低整体速度。
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

    /*
     * 第五步：分别输出到四个车轮。
     */
    MotorControl_SetMotorNormalized(0U, norm_fl);
    MotorControl_SetMotorNormalized(1U, norm_fr);
    MotorControl_SetMotorNormalized(2U, norm_rl);
    MotorControl_SetMotorNormalized(3U, norm_rr);
}

void gimbal_pan_control(int16_t pan_angle_deg)
{
    (void)pan_angle_deg;
}

void MotorControl_ApplyCommand(const RobotCommand *command)
{
    if (command == NULL)
    {
        return;
    }

    if ((!command->command_valid) || command->estop)
    {
        MotorControl_StopAll();
        return;
    }

    MotorControl_SetBodyVelocity(command->vx_mps, command->vy_mps, command->omega_radps);
}
