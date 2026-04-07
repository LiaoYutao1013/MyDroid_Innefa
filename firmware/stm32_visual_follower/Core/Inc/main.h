#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"
#include "app_config.h"

/*
 * main.h
 *
 * 这个文件集中定义板级硬件引脚映射。
 * 这样在 main.c、motor_control.c 等文件里引用时，
 * 不需要反复写死 GPIO 端口和引脚编号。
 *
 * 当前映射以 STM32F407VGT6 + TIM3/TIM4 + USART1 为例。
 */

/* =============================
 * 电机方向控制引脚
 * =============================
 * 每个电机使用两个方向脚：
 * - IN1=1, IN2=0: 正转
 * - IN1=0, IN2=1: 反转
 * - IN1=0, IN2=0: 刹车 / 关闭（视驱动芯片而定）
 */
#define FL_IN1_Pin GPIO_PIN_0
#define FL_IN1_GPIO_Port GPIOC
#define FL_IN2_Pin GPIO_PIN_1
#define FL_IN2_GPIO_Port GPIOC
#define FR_IN1_Pin GPIO_PIN_2
#define FR_IN1_GPIO_Port GPIOC
#define FR_IN2_Pin GPIO_PIN_3
#define FR_IN2_GPIO_Port GPIOC
#define RL_IN1_Pin GPIO_PIN_4
#define RL_IN1_GPIO_Port GPIOC
#define RL_IN2_Pin GPIO_PIN_5
#define RL_IN2_GPIO_Port GPIOC
#define RR_IN1_Pin GPIO_PIN_12
#define RR_IN1_GPIO_Port GPIOB
#define RR_IN2_Pin GPIO_PIN_13
#define RR_IN2_GPIO_Port GPIOB

/* 驱动芯片待机使能脚，例如 TB6612 的 STBY。 */
#define MOTOR_STBY_Pin GPIO_PIN_14
#define MOTOR_STBY_GPIO_Port GPIOB

/* =============================
 * UART 引脚定义
 * =============================
 * 使用 USART1 与 ROCK 3B 通讯：
 * - PA9  : USART1_TX
 * - PA10 : USART1_RX
 */
#define ROCK_UART_TX_Pin GPIO_PIN_9
#define ROCK_UART_TX_GPIO_Port GPIOA
#define ROCK_UART_RX_Pin GPIO_PIN_10
#define ROCK_UART_RX_GPIO_Port GPIOA

/* =============================
 * PWM 引脚定义
 * =============================
 * TIM3 的 4 个通道分别驱动 4 个麦轮电机的 PWM。
 */
#define FL_PWM_Pin GPIO_PIN_6   /* TIM3_CH1 / PA6 */
#define FL_PWM_GPIO_Port GPIOA
#define FR_PWM_Pin GPIO_PIN_7   /* TIM3_CH2 / PA7 */
#define FR_PWM_GPIO_Port GPIOA
#define RL_PWM_Pin GPIO_PIN_0   /* TIM3_CH3 / PB0 */
#define RL_PWM_GPIO_Port GPIOB
#define RR_PWM_Pin GPIO_PIN_1   /* TIM3_CH4 / PB1 */
#define RR_PWM_GPIO_Port GPIOB

/*
 * Pan 云台 PWM 引脚。
 * 当前实际使用 TIM4_CH1 / PB6。
 */
#define PAN_SERVO_Pin GPIO_PIN_6   /* TIM4_CH1 / PB6 */
#define PAN_SERVO_GPIO_Port GPIOB

/*
 * 下面两个 TILT 宏是历史版本遗留定义。
 * 当前 Pan-only 方案中并未使用，但保留它们不会影响功能，
 * 也方便未来如果恢复双轴云台时继续扩展。
 */
#define TILT_SERVO_Pin GPIO_PIN_7  /* TIM4_CH2 / PB7 */
#define TILT_SERVO_GPIO_Port GPIOB

/* 错误处理函数：通常在初始化失败时进入死循环保护。 */
void Error_Handler(void);

/* 时钟初始化函数。 */
void SystemClock_Config(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */