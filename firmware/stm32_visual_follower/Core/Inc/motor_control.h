#ifndef MOTOR_CONTROL_H
#define MOTOR_CONTROL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>

#include "main.h"
#include "protocol.h"

/*
 * motor_control.h
 *
 * 这个模块只做“执行层”工作：
 * 1. 把车体速度命令转换成 4 个麦轮的归一化转速；
 * 2. 把归一化转速进一步落实为 GPIO 方向脚 + PWM 占空比；
 * 3. 保留与上层兼容的命令入口，便于 main.c 直接调用。
 *
 * 当前阶段不做 Pan/云台硬件输出，因此所有接口都只围绕底盘控制。
 */

/*
 * 初始化麦轮控制层。
 *
 * 参数说明：
 * - front_pwm_tim: 当前用于前轴两路 PWM 的定时器，CubeMX 生成结果中对应 TIM1；
 * - rear_pwm_tim : 当前用于后轴两路 PWM 的定时器，CubeMX 生成结果中对应 TIM4。
 */
void MotorControl_Init(TIM_HandleTypeDef *front_pwm_tim, TIM_HandleTypeDef *rear_pwm_tim);

/*
 * 兼容保留接口。
 * 当前 CubeMX 映射中没有独立的电机驱动 STBY/EN 引脚，因此该接口实现为软占位。
 */
void MotorControl_SetDriverEnabled(bool enabled);

/* 立刻停止 4 个麦轮。 */
void MotorControl_StopAll(void);

/*
 * 按车体坐标系速度控制麦轮底盘。
 * - vx_mps: 前进方向线速度，单位 m/s；
 * - vy_mps: 向左方向线速度，单位 m/s；
 * - omega_radps: 逆时针角速度，单位 rad/s。
 */
void MotorControl_SetBodyVelocity(float vx_mps, float vy_mps, float omega_radps);

/*
 * 保留的兼容接口。
 * 当前版本不做云台硬件初始化，因此该函数为 no-op。
 */
void gimbal_pan_control(int16_t pan_angle_deg);

/*
 * 直接执行一帧 RobotCommand。
 * 当前只执行底盘速度字段，Pan 字段仅保留兼容。
 */
void MotorControl_ApplyCommand(const RobotCommand *command);

#ifdef __cplusplus
}
#endif

#endif /* MOTOR_CONTROL_H */
