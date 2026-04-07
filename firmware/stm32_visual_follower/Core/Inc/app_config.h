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
 * 这个文件集中存放整个 STM32 固件中“需要经常调整”的宏定义，
 * 包括：
 * 1. 串口协议相关常量。
 * 2. 底盘尺寸与轮子参数。
 * 3. 电机 PWM 输出范围。
 * 4. Pan 云台舵机的脉宽和角度配置。
 *
 * 这样做的好处：
 * - 后续硬件更换时，只需要修改这里，而不用到处改源文件。
 * - 便于把“算法逻辑”和“硬件标定参数”分开管理。
 */

/* =============================
 * 串口协议配置
 * =============================
 * 当前协议保持固定 16 字节帧长，方便上位机和下位机都使用定长解析。
 */
#define UART_COMMAND_FRAME_SIZE             16U

/*
 * 超时时间，单位毫秒。
 * 如果超过该时间没有收到新的有效控制帧：
 * 1. 底盘立即停车。
 * 2. Pan 云台回到中位。
 */
#define UART_COMMAND_TIMEOUT_MS             500U

/* =============================
 * 麦克纳姆底盘几何参数
 * =============================
 * 这些参数用于逆运动学公式。
 * 单位一律使用国际单位制（米、弧度、秒）。
 */

/*
 * 底盘前后方向半长度 L。
 * 例如如果前后轮轴间距约 0.23 m，则这里取一半 0.115 m。
 */
#define CHASSIS_HALF_LENGTH_M               0.115f

/*
 * 底盘左右方向半宽度 W。
 * 例如左右轮中心距约 0.19 m，则这里取一半 0.095 m。
 */
#define CHASSIS_HALF_WIDTH_M                0.095f

/* 轮子半径 R，单位米。 */
#define WHEEL_RADIUS_M                      0.048f

/* =============================
 * 底盘开环速度上限
 * =============================
 * 没有编码器时，电机控制是开环的。
 * 这些值用于在软件侧约束命令幅度，避免输出过大。
 */
#define MAX_BODY_VX_MPS                     0.80f
#define MAX_BODY_VY_MPS                     0.60f
#define MAX_BODY_OMEGA_RADPS                1.20f

/*
 * 估计的轮子最大角速度，用于把逆运动学结果归一化为 PWM 占空比。
 * 这个值需要在真车上逐步标定。
 */
#define MAX_WHEEL_ANGULAR_SPEED_RADPS       22.00f

/*
 * 电机死区：归一化速度小于这个值时，直接视为停车。
 * 这样可以减少低占空比下电机抖动、啸叫但不转动的问题。
 */
#define MOTOR_ZERO_DEADBAND                 0.03f

/* =============================
 * 电机 PWM 配置
 * =============================
 * 对应 TIM3 的 ARR 配置。
 * 例如定时器频率为 1 MHz，ARR=49，则 PWM 周期约 50 us，即 20 kHz。
 */
#define MOTOR_PWM_PERIOD_COUNTS             49U

/*
 * 为了避免占空比很小时电机完全不转，
 * 这里设置一个最小有效占空比计数值。
 */
#define MOTOR_PWM_MIN_EFFECTIVE_COUNTS      3U

/* =============================
 * Pan 云台 PWM 配置
 * =============================
 * 当前项目只保留水平 Pan 云台。
 * 舵机控制采用标准 50 Hz PWM：
 * - 500 us 通常对应最小角度。
 * - 2500 us 通常对应最大角度。
 */
#define PAN_SERVO_SIGNAL_GPIO_PORT          GPIOB
#define PAN_SERVO_SIGNAL_GPIO_PIN           GPIO_PIN_6
#define PAN_SERVO_TIM                       TIM4
#define PAN_SERVO_CHANNEL                   TIM_CHANNEL_1
#define PAN_SERVO_PWM_FREQ_HZ               50U
#define PAN_SERVO_PWM_PERIOD_US             20000U
#define PAN_SERVO_MIN_PULSE_US              500U
#define PAN_SERVO_MAX_PULSE_US              2500U
#define PAN_SERVO_MIN_DEG                   0
#define PAN_SERVO_MAX_DEG                   180
#define PAN_SERVO_NEUTRAL_DEG               90

/*
 * 如果舵机方向和期望相反，可把该宏改成 1。
 * 这样无需换线，也不用改上位机逻辑。
 */
#define PAN_SERVO_REVERSED                  0U

/* =============================
 * 电机方向翻转配置
 * =============================
 * 如果某个轮子转向与期望不一致，可以只改对应宏，
 * 而不需要改接线或逆运动学公式。
 */
#define FRONT_LEFT_MOTOR_REVERSED           0U
#define FRONT_RIGHT_MOTOR_REVERSED          1U
#define REAR_LEFT_MOTOR_REVERSED            0U
#define REAR_RIGHT_MOTOR_REVERSED           1U

#ifdef __cplusplus
}
#endif

#endif /* APP_CONFIG_H */