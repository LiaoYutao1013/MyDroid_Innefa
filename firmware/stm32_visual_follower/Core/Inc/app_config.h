#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>

/*
 * app_config.h
 *
 * 这个文件集中保存“算法层/控制层会频繁引用，但又不适合写死在业务代码里”的参数。
 * 当前这批核心修复只聚焦麦轮底盘控制，因此这里保留：
 * 1. ROCK 3B <-> STM32 串口协议的基础参数；
 * 2. 麦克纳姆底盘几何参数与开环速度上限；
 * 3. 电机 PWM 的通用约束；
 * 4. Pan 角度的安全范围。
 *
 * 说明：
 * - 现在暂时不做 Pan 舵机的硬件初始化，所以 Pan 相关配置只用于协议解析与安全限幅；
 * - 真正的 PWM 输出与方向引脚映射，放在 main.h / motor_control.c 中处理。
 */

/* =============================
 * 串口协议配置
 * ============================= */

/* 当前上下位机约定为固定 16 字节控制帧。 */
#define UART_COMMAND_FRAME_SIZE             16U

/*
 * 控制帧超时时间。
 * 超过该时间仍未收到新的有效控制帧时，STM32 进入保护状态并停止麦轮运动。
 */
#define UART_COMMAND_TIMEOUT_MS             500U

/* =============================
 * 麦轮底盘几何参数
 * ============================= */

/* 车体前后半轴距 L，单位 m。 */
#define CHASSIS_HALF_LENGTH_M               0.115f

/* 车体左右半轮距 W，单位 m。 */
#define CHASSIS_HALF_WIDTH_M                0.095f

/* 轮子半径 R，单位 m。 */
#define WHEEL_RADIUS_M                      0.048f

/* =============================
 * 底盘开环速度限制
 * ============================= */

/*
 * 当前阶段只打通链路与基础运动控制，还没有闭环速度控制。
 * 因此这些值既是上层约束，也是底层的最终保护边界。
 */
#define MAX_BODY_VX_MPS                     0.80f
#define MAX_BODY_VY_MPS                     0.60f
#define MAX_BODY_OMEGA_RADPS                1.20f

/*
 * 用于把逆运动学输出的轮速映射到 -1.0 ~ 1.0 的归一化占空比。
 * 这是经验值，后续可结合实车标定逐步调整。
 */
#define MAX_WHEEL_ANGULAR_SPEED_RADPS       22.00f

/*
 * 小于该值的归一化命令直接视为 0，避免低占空比抖动、啸叫但不转等问题。
 */
#define MOTOR_ZERO_DEADBAND                 0.03f

/*
 * 某些电机驱动板在占空比过小时无法克服静摩擦。
 * 这里用“占 ARR 的比例”而不是固定计数值，原因是当前 4 个车轮分属两个不同定时器，
 * 每个定时器的 ARR 可能不同，必须按比例换算才不会前后轮行为不一致。
 */
#define MOTOR_PWM_MIN_EFFECTIVE_RATIO       0.05f

/* =============================
 * 电机方向翻转配置
 * ============================= */

/*
 * 若某个轮子的实际旋向与控制定义相反，只改下面的宏即可，不需要改接线或逆运动学公式。
 * 当前默认按“右侧电机机械安装方向相反”处理。
 */
#define FRONT_LEFT_MOTOR_REVERSED           0U
#define FRONT_RIGHT_MOTOR_REVERSED          1U
#define REAR_LEFT_MOTOR_REVERSED            0U
#define REAR_RIGHT_MOTOR_REVERSED           1U

/* =============================
 * Pan 角度范围（当前仅用于协议保护）
 * ============================= */

/*
 * 当前批次暂不初始化云台舵机，但串口协议里仍保留 Pan 字段。
 * 为避免上位机误发异常角度，这里仍对角度做解析限幅。
 */
#define PAN_SERVO_MIN_DEG                   0
#define PAN_SERVO_MAX_DEG                   180
#define PAN_SERVO_NEUTRAL_DEG               90

/* =============================
 * PS2 手柄直连 STM32 旁路控制参数
 * ============================= */

/*
 * PS2 接收器的轮询周期。
 * 常见无线 PS2 接收器在 10~20 ms 轮询下工作比较稳定，
 * 这里取 20 ms，既能保证响应速度，也不会让主循环负担过重。
 */
#define PS2_GAMEPAD_POLL_INTERVAL_MS        20U

/*
 * 如果超过该时间没有读到新的有效手柄帧，就认为手柄或接收器已经断链。
 * 旁路模式下遇到这种情况会直接停车，不会无缝切回 UART，避免产生“失控感”。
 */
#define PS2_GAMEPAD_TIMEOUT_MS              150U

/*
 * PS2 串行时钟的半周期延时，单位 us。
 * 对大多数常见无线接收器，10~15 us 都能稳定工作。
 */
#define PS2_GAMEPAD_CLOCK_DELAY_US          12U

/*
 * 摇杆死区。
 * PS2 模拟摇杆回中后常有轻微抖动，因此需要做一次软件死区处理。
 */
#define PS2_GAMEPAD_AXIS_DEADBAND           0.12f

/*
 * 默认 / 慢速 / 快速 三挡速度系数。
 * - 默认档适合室内联调；
 * - L1 慢速更适合桌面测试；
 * - R1 快速用于地面跑车测试。
 */
#define PS2_GAMEPAD_NORMAL_SCALE            0.60f
#define PS2_GAMEPAD_SLOW_SCALE              0.35f
#define PS2_GAMEPAD_FAST_SCALE              1.00f

#ifdef __cplusplus
}
#endif

#endif /* APP_CONFIG_H */
