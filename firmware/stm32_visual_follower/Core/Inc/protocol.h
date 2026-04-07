#ifndef PROTOCOL_H
#define PROTOCOL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>

/*
 * protocol.h
 *
 * 这个文件定义 ROCK 3B 与 STM32 之间的串口协议接口。
 * 主要包含：
 * 1. 帧头定义。
 * 2. 标志位定义。
 * 3. 解析后得到的 RobotCommand 结构体。
 * 4. 协议初始化、逐字节解析和 CRC 计算接口。
 */

/* 固定帧头，用于帮助下位机在字节流中找到一帧的起点。 */
#define COMMAND_HEADER_0                    0xAAU
#define COMMAND_HEADER_1                    0x55U

/*
 * 标志位定义。
 * 这些标志位被打包在协议帧的 flags 字节中。
 */
#define COMMAND_FLAG_AUTO                   0x01U
#define COMMAND_FLAG_ESTOP                  0x02U
#define COMMAND_FLAG_VALID                  0x04U
#define COMMAND_FLAG_PROTOCOL_V2            0x08U

/*
 * 兼容说明：
 * 1. 旧协议（V1）仍使用 16 字节固定帧：
 *    - bytes 10-11 为 pan_cdeg（0.01 度单位）
 *    - bytes 12-13 为 tilt_cdeg
 * 2. 新协议（V2）仍保持 16 字节总长度不变：
 *    - bytes 10-11 为 pan_angle_deg（int16，单位度）
 *    - bytes 12-13 预留
 * 3. 通过 COMMAND_FLAG_PROTOCOL_V2 区分新旧协议。
 *    这样可以保证：
 *    - 新下位机能兼容旧上位机
 *    - 新上位机也能切换回旧协议模式
 */

typedef struct
{
    /* 帧序号，用于调试丢帧或观察数据流是否连续。 */
    uint8_t sequence;

    /* 当前这帧命令是否来自自动模式。 */
    bool auto_mode;

    /* 当前这帧是否要求急停。 */
    bool estop;

    /* 当前这帧命令是否通过上位机判定为有效。 */
    bool command_valid;

    /* 当前这帧是否使用了 V2 协议格式。 */
    bool protocol_v2;

    /* 底盘速度命令。 */
    float vx_mps;
    float vy_mps;
    float omega_radps;

    /* Pan 云台目标角度，单位度。 */
    int16_t pan_angle_deg;

    /* 解析该帧时记录的系统毫秒计数。 */
    uint32_t last_update_ms;
} RobotCommand;

/* 初始化协议解析器内部状态。 */
void Protocol_Init(void);

/*
 * 逐字节处理串口接收到的数据。
 *
 * 参数说明：
 * - byte: 本次新收到的 1 个字节。
 * - out_command: 如果成功解析出完整帧，则把结果填充到该结构体。
 * - now_ms: 当前系统毫秒计数，用于记录命令时间戳。
 *
 * 返回值：
 * - true: 成功解析出一帧有效命令。
 * - false: 尚未形成完整帧，或 CRC 校验失败。
 */
bool Protocol_ProcessByte(uint8_t byte, RobotCommand *out_command, uint32_t now_ms);

/* 计算 CRC16-CCITT。 */
uint16_t Protocol_Crc16Ccitt(const uint8_t *data, uint16_t length);

#ifdef __cplusplus
}
#endif

#endif /* PROTOCOL_H */