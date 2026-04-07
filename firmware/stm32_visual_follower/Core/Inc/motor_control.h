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
 * 这个文件定义底盘与云台的执行层接口。
 * 上层（例如 main.c）只需要调用这里的函数，
 * 无需关心具体 PWM 寄存器、GPIO 方向脚或逆运动学公式细节。
 */

/*
 * 初始化电机和 Pan 云台控制模块。
 *
 * 参数说明：
 * - motor_tim: 用于 4 路底盘电机 PWM 的定时器句柄。
 * - pan_servo_tim: 用于 Pan 舵机 PWM 的定时器句柄。
 */
void MotorControl_Init(TIM_HandleTypeDef *motor_tim, TIM_HandleTypeDef *pan_servo_tim);

/* 使能或关闭电机驱动芯片。 */
void MotorControl_SetDriverEnabled(bool enabled);

/* 立即停止 4 个底盘电机。 */
void MotorControl_StopAll(void);

/*
 * 以车体坐标系速度控制麦轮底盘。
 *
 * 参数说明：
 * - vx_mps: 前进方向线速度，单位 m/s。
 * - vy_mps: 左移方向线速度，单位 m/s。
 * - omega_radps: 绕 z 轴逆时针角速度，单位 rad/s。
 */
void MotorControl_SetBodyVelocity(float vx_mps, float vy_mps, float omega_radps);

/* 控制 Pan 云台到目标角度。 */
void gimbal_pan_control(int16_t pan_angle_deg);

/*
 * 直接按一帧 RobotCommand 执行动作。
 *
 * 这个接口保留下来，便于后续如果想把应用层控制逻辑封装在这里，
 * 可以减少 main.c 中的判断代码。
 */
void MotorControl_ApplyCommand(const RobotCommand *command);

#ifdef __cplusplus
}
#endif

#endif /* MOTOR_CONTROL_H */