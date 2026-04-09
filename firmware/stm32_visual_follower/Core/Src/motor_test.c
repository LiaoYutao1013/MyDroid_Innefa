/*
 * motor_test.c
 *
 * 电机独立测试模块实现
 *
 * UART命令格式:
 *   M <motor_id> <duty>      - 设置单电机 (M 0 500 -> 50%)
 *   E <motor_id>              - 查询编码器 (E 0)
 *   S                         - 停止所有电机
 *   X                         - 紧急停止
 *   R <motor_id>              - 重置编码器
 *   C <motor_id> <factor>     - 设置补偿系数 (C 0 0.95)
 *   H                         - 打印帮助信息
 */

#include "motor_test.h"
#include "main.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

/* ============ 配置常量 ============ */

#define MOTOR_COUNT             4
#define ENCODER_SAMPLE_TIME_MS  10          // 编码器采样间隔
#define UART_RX_BUFFER_SIZE     64

#define MOTOR_ZERO_DEADBAND     0.05f       // PWM死区 (5%)
#define MOTOR_PWM_PERIOD        1000        // PWM周期计数，对应 0-100%

/* ============ 静态数据 ============ */

static struct {
    TIM_HandleTypeDef *motor_tim;
    TIM_HandleTypeDef *encoder_tims[4];

    // 电机状态
    struct {
        int16_t pwm_duty;           // 当前PWM占空比 (-1000~1000)
        int32_t encoder_count;      // 当前编码器计数
        int32_t encoder_last_count; // 上一周期计数
        int16_t encoder_rpm;        // 当前转速
        float speed_factor;         // 补偿系数 (0.5~2.0)
        uint16_t encoder_ppr;       // 每圈脉冲数 (PPR)
        uint32_t last_update_ms;    // 最后更新时间
    } motors[4];

    // UART接收缓冲
    struct {
        uint8_t buffer[UART_RX_BUFFER_SIZE];
        uint8_t index;
        char last_command[UART_RX_BUFFER_SIZE];
    } uart;

    // 诊断信息
    struct {
        bool overcurrent;
        bool encoder_error;
    } diag[4];
} s_motor_test;

/* ============ 内部函数声明 ============ */

static void _update_encoder_values(uint32_t now_ms);
static void _apply_motor_pwm(uint8_t motor_id, int16_t duty);
static void _parse_uart_command(void);
static void _print_status(uint8_t motor_id);

/* ============ 公开API实现 ============ */

void MotorTest_Init(TIM_HandleTypeDef *motor_tim, TIM_HandleTypeDef **encoder_tims)
{
    memset(&s_motor_test, 0, sizeof(s_motor_test));

    s_motor_test.motor_tim = motor_tim;
    for (int i = 0; i < 4; i++) {
        s_motor_test.encoder_tims[i] = encoder_tims[i];
        s_motor_test.motors[i].speed_factor = 1.0f;
        s_motor_test.motors[i].encoder_ppr = 20;  // 520电机默认PPR
    }

    /* 启动所有PWM和编码器TIM */
    HAL_TIM_PWM_Start(motor_tim, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(motor_tim, TIM_CHANNEL_2);
    HAL_TIM_PWM_Start(motor_tim, TIM_CHANNEL_3);
    HAL_TIM_PWM_Start(motor_tim, TIM_CHANNEL_4);

    for (int i = 0; i < 4; i++) {
        if (encoder_tims[i] != NULL) {
            __HAL_TIM_ENABLE(encoder_tims[i]);  // 启用QEI模式
        }
    }

    MotorTest_StopAll();

    printf("MotorTest initialized.\r\n");
    printf("Type 'H' for help.\r\n");
}

int MotorTest_SetMotor(uint8_t motor_id, int16_t duty)
{
    if (motor_id >= 4) {
        return -1;
    }

    s_motor_test.motors[motor_id].pwm_duty = duty;
    _apply_motor_pwm(motor_id, duty);

    return 0;
}

void MotorTest_SetAllMotors(int16_t duty_fl, int16_t duty_fr,
                             int16_t duty_rl, int16_t duty_rr)
{
    MotorTest_SetMotor(0, duty_fl);
    MotorTest_SetMotor(1, duty_fr);
    MotorTest_SetMotor(2, duty_rl);
    MotorTest_SetMotor(3, duty_rr);
}

void MotorTest_StopAll(void)
{
    for (int i = 0; i < 4; i++) {
        MotorTest_SetMotor(i, 0);
    }
}

void MotorTest_EmergencyStop(void)
{
    /* 断开驱动器使能脚 */
    HAL_GPIO_WritePin(MOTOR_STBY_GPIO_Port, MOTOR_STBY_Pin, GPIO_PIN_RESET);
    MotorTest_StopAll();
    printf("EMERGENCY STOP\r\n");
}

MotorStatus MotorTest_GetStatus(uint8_t motor_id)
{
    MotorStatus status = {0};

    if (motor_id < 4) {
        status.motor_id = motor_id;
        status.pwm_duty = s_motor_test.motors[motor_id].pwm_duty;
        status.encoder_count = s_motor_test.motors[motor_id].encoder_count;
        status.encoder_rpm = s_motor_test.motors[motor_id].encoder_rpm;
        status.motor_enabled = true;
    }

    return status;
}

SystemState MotorTest_GetSystemState(void)
{
    SystemState state = {0};
    state.timestamp_ms = HAL_GetTick();

    for (int i = 0; i < 4; i++) {
        state.motors[i] = MotorTest_GetStatus(i);
    }

    return state;
}

void MotorTest_ResetEncoder(uint8_t motor_id)
{
    if (motor_id < 4 && s_motor_test.encoder_tims[motor_id] != NULL) {
        __HAL_TIM_SET_COUNTER(s_motor_test.encoder_tims[motor_id], 0);
        s_motor_test.motors[motor_id].encoder_count = 0;
        s_motor_test.motors[motor_id].encoder_last_count = 0;
    }
}

void MotorTest_ResetAllEncoders(void)
{
    for (int i = 0; i < 4; i++) {
        MotorTest_ResetEncoder(i);
    }
}

void MotorTest_SetSpeedFactor(uint8_t motor_id, float factor)
{
    if (motor_id < 4) {
        if (factor < 0.5f) factor = 0.5f;
        if (factor > 2.0f) factor = 2.0f;
        s_motor_test.motors[motor_id].speed_factor = factor;
    }
}

void MotorTest_SetEncoderPPR(uint8_t motor_id, uint16_t ppr)
{
    if (motor_id < 4 && ppr > 0) {
        s_motor_test.motors[motor_id].encoder_ppr = ppr;
    }
}

MotorDiagnostics MotorTest_GetDiagnostics(uint8_t motor_id)
{
    MotorDiagnostics diag = {0};

    if (motor_id < 4) {
        diag.overcurrent_flag = s_motor_test.diag[motor_id].overcurrent;
        diag.encoder_error_flag = s_motor_test.diag[motor_id].encoder_error;

        // 简单过流检测：连续高PWM可能触发
        if (abs(s_motor_test.motors[motor_id].pwm_duty) > 900) {
            diag.avg_current_ma = 3000;  // 降低占空比以避免过流
        }
    }

    return diag;
}

void MotorTest_ProcessUARTByte(uint8_t byte)
{
    uint8_t *buf = s_motor_test.uart.buffer;
    uint8_t *idx = &s_motor_test.uart.index;

    if (byte == '\r' || byte == '\n') {
        if (*idx > 0) {
            _parse_uart_command();
            *idx = 0;
        }
        return;
    }

    if (*idx < UART_RX_BUFFER_SIZE - 1) {
        buf[(*idx)++] = byte;
        buf[*idx] = '\0';
    }
}

const char* MotorTest_GetLastUARTCommand(void)
{
    return s_motor_test.uart.last_command;
}

/* ============ 内部函数实现 ============ */

static void _apply_motor_pwm(uint8_t motor_id, int16_t duty)
{
    if (motor_id >= 4 || s_motor_test.motor_tim == NULL) {
        return;
    }

    // 限幅
    if (duty < -1000) duty = -1000;
    if (duty > 1000) duty = 1000;

    // 死区
    if (abs(duty) < (int16_t)(MOTOR_ZERO_DEADBAND * 1000)) {
        duty = 0;
    }

    // 转换到PWM占空比
    uint32_t pwm_value = (uint32_t)(abs(duty) * MOTOR_PWM_PERIOD / 1000);
    uint32_t tim_channel = TIM_CHANNEL_1 + motor_id;

    // 设置方向GPIO (IN1/IN2)
    GPIO_PinState in1, in2;
    if (duty > 0) {
        in1 = GPIO_PIN_SET;     // 正转
        in2 = GPIO_PIN_RESET;
    } else if (duty < 0) {
        in1 = GPIO_PIN_RESET;   // 反转
        in2 = GPIO_PIN_SET;
    } else {
        in1 = GPIO_PIN_RESET;   // 停止
        in2 = GPIO_PIN_RESET;
        pwm_value = 0;
    }

    // 获取GPIO端口（这里硬编码，实际项目应使用app_config.h中的宏）
    // 示例：
    static GPIO_TypeDef *in1_ports[4] = {FL_IN1_GPIO_Port, FR_IN1_GPIO_Port, RL_IN1_GPIO_Port, RR_IN1_GPIO_Port};
    static uint16_t in1_pins[4] = {FL_IN1_Pin, FR_IN1_Pin, RL_IN1_Pin, RR_IN1_Pin};
    static GPIO_TypeDef *in2_ports[4] = {FL_IN2_GPIO_Port, FR_IN2_GPIO_Port, RL_IN2_GPIO_Port, RR_IN2_GPIO_Port};
    static uint16_t in2_pins[4] = {FL_IN2_Pin, FR_IN2_Pin, RL_IN2_Pin, RR_IN2_Pin};

    HAL_GPIO_WritePin(in1_ports[motor_id], in1_pins[motor_id], in1);
    HAL_GPIO_WritePin(in2_ports[motor_id], in2_pins[motor_id], in2);

    // 设置PWM占空比
    __HAL_TIM_SET_COMPARE(s_motor_test.motor_tim, tim_channel, pwm_value);
}

static void _update_encoder_values(uint32_t now_ms)
{
    for (int i = 0; i < 4; i++) {
        if (s_motor_test.encoder_tims[i] == NULL) {
            continue;
        }

        // 获取当前计数
        int32_t current_count = (int32_t)__HAL_TIM_GET_COUNTER(s_motor_test.encoder_tims[i]);
        int32_t delta = current_count - s_motor_test.motors[i].encoder_last_count;

        // 转换为RPM
        // RPM = (delta_pulses / PPR) * (60000 / sample_time_ms) * speed_factor
        uint16_t ppr = s_motor_test.motors[i].encoder_ppr;
        uint32_t dt = now_ms - s_motor_test.motors[i].last_update_ms;
        if (dt == 0) dt = 1;

        if (ppr > 0 && dt > 0) {
            float delta_revs = (float)delta / ppr;
            float revs_per_minute = (delta_revs * 60000.0f) / dt;
            s_motor_test.motors[i].encoder_rpm = (int16_t)revs_per_minute;
        }

        s_motor_test.motors[i].encoder_count = current_count;
        s_motor_test.motors[i].encoder_last_count = current_count;
        s_motor_test.motors[i].last_update_ms = now_ms;
    }
}

static void _parse_uart_command(void)
{
    uint8_t *buf = s_motor_test.uart.buffer;
    int motor_id, duty, factor;
    uint16_t ppr;

    // 保存命令历史（用于debug）
    strncpy(s_motor_test.uart.last_command, (const char*)buf,
            sizeof(s_motor_test.uart.last_command) - 1);

    if (buf[0] == '\0') {
        return;
    }

    char cmd = buf[0];

    switch (cmd) {
        case 'M':  // 设置电机: M <motor_id> <duty>
            if (sscanf((const char*)buf, "M %d %d", &motor_id, &duty) == 2) {
                MotorTest_SetMotor(motor_id, duty);
                printf("M %d %d OK\r\n", motor_id, duty);
                _print_status(motor_id);
            } else {
                printf("M: Invalid format. Use: M <0-3> <-1000~1000>\r\n");
            }
            break;

        case 'E':  // 查询编码器: E <motor_id>
            if (sscanf((const char*)buf, "E %d", &motor_id) == 1 && motor_id < 4) {
                _update_encoder_values(HAL_GetTick());
                MotorStatus status = MotorTest_GetStatus(motor_id);
                printf("E %d: count=%ld rpm=%d\r\n", motor_id,
                       status.encoder_count, status.encoder_rpm);
            } else {
                printf("E: Invalid format. Use: E <0-3>\r\n");
            }
            break;

        case 'S':  // 停止: S
            MotorTest_StopAll();
            printf("All motors stopped.\r\n");
            break;

        case 'X':  // 紧急停止: X
            MotorTest_EmergencyStop();
            break;

        case 'R':  // 重置编码器: R <motor_id> 或 R all
            if (buf[2] == 'a') {
                MotorTest_ResetAllEncoders();
                printf("All encoders reset.\r\n");
            } else if (sscanf((const char*)buf, "R %d", &motor_id) == 1 && motor_id < 4) {
                MotorTest_ResetEncoder(motor_id);
                printf("Motor %d encoder reset.\r\n", motor_id);
            }
            break;

        case 'C':  // 补偿系数: C <motor_id> <factor>
            if (sscanf((const char*)buf, "C %d %d", &motor_id, &factor) == 2) {
                float f = factor / 100.0f;
                MotorTest_SetSpeedFactor(motor_id, f);
                printf("Motor %d speed factor set to %.2f\r\n", motor_id, f);
            }
            break;

        case 'P':  // PPR设置: P <motor_id> <ppr>
            if (sscanf((const char*)buf, "P %d %hu", &motor_id, &ppr) == 2 && ppr > 0) {
                MotorTest_SetEncoderPPR(motor_id, ppr);
                printf("Motor %d PPR set to %u\r\n", motor_id, ppr);
            }
            break;

        case 'H':  // 帮助: H
        case '?':
            printf("\r\n=== Motor Test Commands ===\r\n");
            printf("M <id> <duty>    - Set motor (id: 0-3, duty: -1000~1000)\r\n");
            printf("E <id>            - Get encoder (id: 0-3)\r\n");
            printf("S                 - Stop all motors\r\n");
            printf("X                 - Emergency stop\r\n");
            printf("R <id>|all        - Reset encoder\r\n");
            printf("C <id> <factor>   - Set speed factor (factor: 50~200)\r\n");
            printf("P <id> <ppr>      - Set PPR (pulses per rev)\r\n");
            printf("D <id>            - Diagnostics\r\n");
            printf("H or ?            - Help\r\n");
            printf("=========================\r\n");
            break;

        case 'D':  // 诊断: D <motor_id>
            if (sscanf((const char*)buf, "D %d", &motor_id) == 1 && motor_id < 4) {
                MotorDiagnostics d = MotorTest_GetDiagnostics(motor_id);
                printf("Motor %d Diagnostics:\r\n", motor_id);
                printf("  Overcurrent: %s\r\n", d.overcurrent_flag ? "YES" : "NO");
                printf("  Encoder Error: %s\r\n", d.encoder_error_flag ? "YES" : "NO");
                printf("  Avg Current: %.1f mA\r\n", d.avg_current_ma);
            }
            break;

        default:
            printf("Unknown command: '%s'. Type 'H' for help.\r\n", (const char*)buf);
    }
}

static void _print_status(uint8_t motor_id)
{
    if (motor_id >= 4) return;

    MotorStatus status = MotorTest_GetStatus(motor_id);
    printf("  Duty: %d/1000 (%d%%)\r\n", status.pwm_duty,
           abs(status.pwm_duty) / 10);
    printf("  Encoder: count=%ld rpm=%d\r\n",
           status.encoder_count, status.encoder_rpm);
}

/**
 * 应在定时器中断中调用（周期 >= 10ms）
 * 用于定期更新编码器值和计算转速
 */
void MotorTest_PeriodicUpdate(void)
{
    static uint32_t last_update = 0;
    uint32_t now = HAL_GetTick();

    if (now - last_update >= ENCODER_SAMPLE_TIME_MS) {
        _update_encoder_values(now);
        last_update = now;
    }
}

/* ============ UART中断回调（需在main.c中配置） ============ */

/**
 * 在 HAL_UART_RxCpltCallback() 中调用此函数
 * 或在接收中断处理中逐字节调用
 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        // 读取一个字节（假设在中断中配置了单字节接收模式）
        uint8_t ch;
        if (HAL_UART_Receive(huart, &ch, 1, HAL_MAX_DELAY) == HAL_OK) {
            MotorTest_ProcessUARTByte(ch);
        }
    }
}
