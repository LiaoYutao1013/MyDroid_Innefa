/*
 * motor_test_config.h
 *
 * 电机测试模块配置文件
 * 根据你的硬件配置修改下面的宏定义
 */

#ifndef MOTOR_TEST_CONFIG_H
#define MOTOR_TEST_CONFIG_H

/* ============ PWM配置 ============ */

// PWM定时器 (TIM2 用于 FL, FR; TIM3 用于 RL, RR)
#define MOTOR_PWM_TIMER         TIM2
#define MOTOR_PWM_FREQ_HZ       20000       // PWM频率 20kHz
#define MOTOR_PWM_PERIOD_COUNTS 1000        // PWM周期计数 (对应0-100%)
#define MOTOR_PWM_MIN_EFFECTIVE_COUNTS 50   // 最小有效PWM值 (5%)

// PWM死区
#define MOTOR_ZERO_DEADBAND     0.05f       // 低于5%占空比视为停止

/* ============ 编码器配置 ============ */

// 编码器定时器 (QEI模式)
#define ENCODER_TIM_FL          TIM2        // 前左轮编码器
#define ENCODER_TIM_FR          TIM3        // 前右轮编码器
#define ENCODER_TIM_RL          TIM4        // 后左轮编码器
#define ENCODER_TIM_RR          TIM5        // 后右轮编码器

// 编码器参数
#define MOTOR_ENCODER_PPR       20          // 每圈脉冲数 (Pulses Per Revolution)
#define ENCODER_SAMPLE_TIME_MS  10          // 采样周期

/* ============ GPIO引脚配置 ============ */

// 前左轮 (FL) - Motor 0
#define FL_IN1_GPIO_Port        GPIOA
#define FL_IN1_Pin              GPIO_PIN_5
#define FL_IN2_GPIO_Port        GPIOA
#define FL_IN2_Pin              GPIO_PIN_6
#define FL_REVERSED             0           // 反向标志: 0=正常, 1=反向

// 前右轮 (FR) - Motor 1
#define FR_IN1_GPIO_Port        GPIOA
#define FR_IN1_Pin              GPIO_PIN_7
#define FR_IN2_GPIO_Port        GPIOB
#define FR_IN2_Pin              GPIO_PIN_5
#define FR_REVERSED             0

// 后左轮 (RL) - Motor 2
#define RL_IN1_GPIO_Port        GPIOB
#define RL_IN1_Pin              GPIO_PIN_10
#define RL_IN2_GPIO_Port        GPIOB
#define RL_IN2_Pin              GPIO_PIN_11
#define RL_REVERSED             0

// 后右轮 (RR) - Motor 3
#define RR_IN1_GPIO_Port        GPIOB
#define RR_IN1_Pin              GPIO_PIN_12
#define RR_IN2_GPIO_Port        GPIOB
#define RR_IN2_Pin              GPIO_PIN_13
#define RR_REVERSED             0

// 电机驱动器使能脚
#define MOTOR_STBY_GPIO_Port    GPIOA
#define MOTOR_STBY_Pin          GPIO_PIN_4

/* ============ UART配置 ============ */

#define TEST_UART_Handle        USART1      // 用于命令接收
#define TEST_UART_BAUD          115200

/* ============ 性能参数 ============ */

// 最大转速（用于限幅）
#define MAX_WHEEL_RPM           250         // 525电机标称转速

// 防护限值
#define MOTOR_OVERCURRENT_MA    3500        // 过电流阈值 (mA)
#define MOTOR_MAX_CONTINUOUS_DUTY 900       // 连续最大占空比 (90%)

#endif /* MOTOR_TEST_CONFIG_H */
