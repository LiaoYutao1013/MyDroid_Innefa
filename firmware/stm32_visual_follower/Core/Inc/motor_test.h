/*
 * motor_test.h
 *
 * 电机独立测试模块 - 简化版，无需ROS2依赖
 * 功能：
 * - 直接控制4个电机（PWM + 方向）
 * - 读取编码器反馈
 * - 通过UART解析简单命令
 */

#ifndef MOTOR_TEST_H
#define MOTOR_TEST_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stdbool.h>

/* ============ 数据结构定义 ============ */

typedef struct {
    uint8_t motor_id;           // 0:FL, 1:FR, 2:RL, 3:RR
    int16_t pwm_duty;           // -1000~1000 (0.1% 分辨率)
    int32_t encoder_count;      // 编码器脉冲数
    int16_t encoder_rpm;        // 转速 (RPM)
    bool motor_enabled;         // 电机是否由驱动器使能
} MotorStatus;

typedef struct {
    uint32_t timestamp_ms;      // 时间戳
    MotorStatus motors[4];      // 4个电机状态
} SystemState;

/* ============ 初始化函数 ============ */

/**
 * 初始化电机测试模块
 * 应在 main() 中调用一次
 *
 * 参数：
 *   motor_tim: 4路电机PWM定时器句柄 (TIM2/TIM3)
 *   encoder_tims: 编码器定时器句柄组指针 {TIM2, TIM3, ...}
 */
void MotorTest_Init(TIM_HandleTypeDef *motor_tim, TIM_HandleTypeDef **encoder_tims);

/* ============ 电机控制函数 ============ */

/**
 * 设置单个电机速度
 *
 * 参数：
 *   motor_id: 0~3 (0:FL, 1:FR, 2:RL, 3:RR)
 *   duty:     -1000~1000 (-100%~100%)
 *
 * 返回值：
 *   0 成功, -1 参数错误
 */
int MotorTest_SetMotor(uint8_t motor_id, int16_t duty);

/**
 * 同时设置4个电机速度
 */
void MotorTest_SetAllMotors(int16_t duty_fl, int16_t duty_fr,
                             int16_t duty_rl, int16_t duty_rr);

/**
 * 停止所有电机
 */
void MotorTest_StopAll(void);

/**
 * 紧急停止（断开驱动器使能）
 */
void MotorTest_EmergencyStop(void);

/* ============ 编码器反馈函数 ============ */

/**
 * 获取单个电机状态（包括编码器计数和转速）
 */
MotorStatus MotorTest_GetStatus(uint8_t motor_id);

/**
 * 获取系统整体状态
 */
SystemState MotorTest_GetSystemState(void);

/**
 * 重置单个电机编码器计数和转速
 */
void MotorTest_ResetEncoder(uint8_t motor_id);

/**
 * 重置所有编码器
 */
void MotorTest_ResetAllEncoders(void);

/* ============ 配置函数 ============ */

/**
 * 设置电机的转向补偿系数
 * 用于校准转速差异
 *
 * 参数：
 *   factor: 0.50~2.00，默认 1.00
 */
void MotorTest_SetSpeedFactor(uint8_t motor_id, float factor);

/**
 * 设置编码器的PPR（每圈脉冲数）
 * 默认值：20（520电机标准值）
 */
void MotorTest_SetEncoderPPR(uint8_t motor_id, uint16_t ppr);

/**
 * 诊断和监测函数
 */
typedef struct {
    bool overcurrent_flag;      // 过电流标志
    bool encoder_error_flag;    // 编码器异常标志
    uint16_t error_code;        // 错误代码
    float avg_current_ma;       // 平均电流 (如配置了ADC)
} MotorDiagnostics;

MotorDiagnostics MotorTest_GetDiagnostics(uint8_t motor_id);

/* ============ UART命令解析 ============ */

/**
 * 处理UART接收到的字节
 * 应在中断处理函数中逐字节调用
 */
void MotorTest_ProcessUARTByte(uint8_t byte);

/**
 * 获取最后一条UART命令解析的结果
 * 用于debug
 */
const char* MotorTest_GetLastUARTCommand(void);

/* ============ 中断回调 ============ */

/**
 * 编码器脉冲更新回调（可选）
 * 在高速运行时，可以从TIM的DMA中断中调用
 */
void MotorTest_OnEncoderUpdate(uint8_t motor_id, int32_t delta_count);

#ifdef __cplusplus
}
#endif

#endif /* MOTOR_TEST_H */
