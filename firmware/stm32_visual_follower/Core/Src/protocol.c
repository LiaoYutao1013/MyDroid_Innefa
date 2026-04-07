#include "protocol.h"
#include "app_config.h"

#include <string.h>

/*
 * protocol.c
 *
 * 这里实现串口协议的逐字节解析。
 * 设计目标：
 * 1. 即使数据流中间出现错误字节，也能重新同步到帧头。
 * 2. 支持固定长度帧，减少解析复杂度。
 * 3. 同时兼容旧协议和新协议。
 */

/* 帧缓冲区：用于暂存一整帧数据。 */
static uint8_t s_frame_buffer[UART_COMMAND_FRAME_SIZE];

/* 当前已经收集到的字节数。 */
static uint8_t s_frame_index = 0U;

/* 从小端字节流中读取 int16。 */
static int16_t Protocol_ReadInt16Le(const uint8_t *data)
{
    return (int16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

/* 从小端字节流中读取 uint16。 */
static uint16_t Protocol_ReadUint16Le(const uint8_t *data)
{
    return (uint16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

/*
 * 把解析出的 Pan 角度限制在安全范围内。
 * 即使上位机发出异常值，这里也会二次保护。
 */
static int16_t Protocol_ClampPanAngle(int32_t angle_deg)
{
    if (angle_deg < PAN_SERVO_MIN_DEG)
    {
        return PAN_SERVO_MIN_DEG;
    }
    if (angle_deg > PAN_SERVO_MAX_DEG)
    {
        return PAN_SERVO_MAX_DEG;
    }
    return (int16_t)angle_deg;
}

void Protocol_Init(void)
{
    /* 启动前清空缓冲区和解析状态。 */
    memset(s_frame_buffer, 0, sizeof(s_frame_buffer));
    s_frame_index = 0U;
}

bool Protocol_ProcessByte(uint8_t byte, RobotCommand *out_command, uint32_t now_ms)
{
    if (out_command == NULL)
    {
        return false;
    }

    /*
     * 第 1 步：等待第一个帧头字节 0xAA。
     * 如果当前不是帧头，直接丢弃。
     */
    if (s_frame_index == 0U)
    {
        if (byte == COMMAND_HEADER_0)
        {
            s_frame_buffer[s_frame_index++] = byte;
        }
        return false;
    }

    /*
     * 第 2 步：等待第二个帧头字节 0x55。
     * 如果发现又来了一个 0xAA，说明可能是新帧开始，保留它继续等待。
     */
    if (s_frame_index == 1U)
    {
        if (byte == COMMAND_HEADER_1)
        {
            s_frame_buffer[s_frame_index++] = byte;
        }
        else if (byte == COMMAND_HEADER_0)
        {
            s_frame_buffer[0] = COMMAND_HEADER_0;
            s_frame_index = 1U;
        }
        else
        {
            s_frame_index = 0U;
        }
        return false;
    }

    /* 第 3 步：继续收集后续字节，直到构成完整的 16 字节帧。 */
    s_frame_buffer[s_frame_index++] = byte;
    if (s_frame_index < UART_COMMAND_FRAME_SIZE)
    {
        return false;
    }

    /* 已经收满一帧，准备开始解析。 */
    s_frame_index = 0U;

    /*
     * CRC 仍然覆盖前 14 个字节。
     * 这样即使协议从 V1 演进到 V2，也不需要改帧长和 CRC 位置。
     */
    const uint16_t received_crc = Protocol_ReadUint16Le(&s_frame_buffer[14]);
    const uint16_t calculated_crc = Protocol_Crc16Ccitt(s_frame_buffer, 14U);
    if (received_crc != calculated_crc)
    {
        return false;
    }

    /* 解析通用字段。 */
    out_command->sequence = s_frame_buffer[2];
    out_command->auto_mode = (s_frame_buffer[3] & COMMAND_FLAG_AUTO) != 0U;
    out_command->estop = (s_frame_buffer[3] & COMMAND_FLAG_ESTOP) != 0U;
    out_command->command_valid = (s_frame_buffer[3] & COMMAND_FLAG_VALID) != 0U;
    out_command->protocol_v2 = (s_frame_buffer[3] & COMMAND_FLAG_PROTOCOL_V2) != 0U;
    out_command->vx_mps = (float)Protocol_ReadInt16Le(&s_frame_buffer[4]) / 1000.0f;
    out_command->vy_mps = (float)Protocol_ReadInt16Le(&s_frame_buffer[6]) / 1000.0f;
    out_command->omega_radps = (float)Protocol_ReadInt16Le(&s_frame_buffer[8]) / 1000.0f;

    if (out_command->protocol_v2)
    {
        /*
         * 新协议：bytes 10-11 直接表示整数角度。
         * 例如 90 表示 90 度。
         */
        const int16_t raw_pan_angle_deg = Protocol_ReadInt16Le(&s_frame_buffer[10]);
        out_command->pan_angle_deg = Protocol_ClampPanAngle(raw_pan_angle_deg);
    }
    else
    {
        /*
         * 旧协议：bytes 10-11 为 0.01 度单位的 pan_cdeg。
         * 例如 9000 表示 90.00 度。
         * 这里把它四舍五入转换成整数角度，供 Pan-only 控制逻辑直接使用。
         */
        const int16_t raw_pan_cdeg = Protocol_ReadInt16Le(&s_frame_buffer[10]);
        out_command->pan_angle_deg = Protocol_ClampPanAngle((raw_pan_cdeg + 50) / 100);
    }

    /* 记录这条命令被成功解析的时间。 */
    out_command->last_update_ms = now_ms;
    return true;
}

uint16_t Protocol_Crc16Ccitt(const uint8_t *data, uint16_t length)
{
    uint16_t crc = 0xFFFFU;
    uint16_t i;
    uint8_t bit;

    for (i = 0U; i < length; ++i)
    {
        crc ^= (uint16_t)data[i] << 8;
        for (bit = 0U; bit < 8U; ++bit)
        {
            if ((crc & 0x8000U) != 0U)
            {
                crc = (uint16_t)((crc << 1) ^ 0x1021U);
            }
            else
            {
                crc <<= 1;
            }
        }
    }

    return crc;
}