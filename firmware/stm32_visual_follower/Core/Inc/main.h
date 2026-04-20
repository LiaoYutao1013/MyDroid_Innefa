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
 * 这个文件只负责保存“当前固件真实使用的 CubeMX 硬件映射”。
 * 这次修复后的映射基于当前工程里的 CubeMX 生成结果，而不是旧文档里的历史引脚定义。
 *
 * 当前麦轮控制相关映射如下：
 * 1. 前轮 PWM：TIM1_CH1(PE9)、TIM1_CH4(PE14)
 * 2. 后轮 PWM：TIM4_CH1(PD12)、TIM4_CH4(PD15)
 * 3. 8 个方向脚：PB10/PB11/PB12/PB13/PB4/PB7/PB8/PA12
 * 4. 串口：USART1_TX(PA9)、USART1_RX(PA10)
 * 5. PS2 手柄旁路输入：PC0~PC3（软件时序 SPI）
 *
 * 重要说明：
 * - 当前阶段只做麦轮底盘控制；
 * - Pan/云台硬件初始化暂不启用，因此这里不再保留舵机 PWM 引脚宏。
 */

/* =============================
 * 麦轮方向控制引脚
 * ============================= */

/* 前左轮：PB10 / PB11 */
#define FL_IN1_Pin                          GPIO_PIN_10
#define FL_IN1_GPIO_Port                    GPIOB
#define FL_IN2_Pin                          GPIO_PIN_11
#define FL_IN2_GPIO_Port                    GPIOB

/* 前右轮：PB12 / PB13 */
#define FR_IN1_Pin                          GPIO_PIN_12
#define FR_IN1_GPIO_Port                    GPIOB
#define FR_IN2_Pin                          GPIO_PIN_13
#define FR_IN2_GPIO_Port                    GPIOB

/* 后左轮：PB4 / PB7 */
#define RL_IN1_Pin                          GPIO_PIN_4
#define RL_IN1_GPIO_Port                    GPIOB
#define RL_IN2_Pin                          GPIO_PIN_7
#define RL_IN2_GPIO_Port                    GPIOB

/* 后右轮：PB8 / PA12 */
#define RR_IN1_Pin                          GPIO_PIN_8
#define RR_IN1_GPIO_Port                    GPIOB
#define RR_IN2_Pin                          GPIO_PIN_12
#define RR_IN2_GPIO_Port                    GPIOA

/* =============================
 * 麦轮 PWM 输出引脚
 * ============================= */

/* 前左轮 PWM：TIM1_CH1 / PE9 */
#define FL_PWM_Pin                          GPIO_PIN_9
#define FL_PWM_GPIO_Port                    GPIOE

/* 前右轮 PWM：TIM1_CH4 / PE14 */
#define FR_PWM_Pin                          GPIO_PIN_14
#define FR_PWM_GPIO_Port                    GPIOE

/* 后左轮 PWM：TIM4_CH1 / PD12 */
#define RL_PWM_Pin                          GPIO_PIN_12
#define RL_PWM_GPIO_Port                    GPIOD

/* 后右轮 PWM：TIM4_CH4 / PD15 */
#define RR_PWM_Pin                          GPIO_PIN_15
#define RR_PWM_GPIO_Port                    GPIOD

/* =============================
 * USART1 通讯引脚
 * ============================= */

#define ROCK_UART_TX_Pin                    GPIO_PIN_9
#define ROCK_UART_TX_GPIO_Port              GPIOA
#define ROCK_UART_RX_Pin                    GPIO_PIN_10
#define ROCK_UART_RX_GPIO_Port              GPIOA

/* =============================
 * PS2 手柄接收器接口
 * ============================= */

/*
 * 这 4 根线使用软件时序方式驱动，因此不依赖额外 SPI 外设。
 * 代码默认使用当前 CubeMX 未占用的 PC0~PC3。
 * 如果你的实物已经焊到其他空闲 GPIO，只需要改下面 4 组宏即可。
 */

/* ATT / CS：STM32 拉低后开始一次 PS2 帧传输。 */
#define PS2_ATT_Pin                         GPIO_PIN_0
#define PS2_ATT_GPIO_Port                   GPIOC

/* CMD：STM32 发给接收器的命令数据线。 */
#define PS2_CMD_Pin                         GPIO_PIN_1
#define PS2_CMD_GPIO_Port                   GPIOC

/* CLK：STM32 输出给接收器的串行时钟。 */
#define PS2_CLK_Pin                         GPIO_PIN_2
#define PS2_CLK_GPIO_Port                   GPIOC

/* DAT：接收器返回给 STM32 的数据线。 */
#define PS2_DAT_Pin                         GPIO_PIN_3
#define PS2_DAT_GPIO_Port                   GPIOC

void Error_Handler(void);
void SystemClock_Config(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
