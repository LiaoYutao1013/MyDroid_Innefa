#ifndef PS2_GAMEPAD_H
#define PS2_GAMEPAD_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdbool.h>
#include <stdint.h>

#include "main.h"

/*
 * ps2_gamepad.h
 *
 * 这个模块负责与 PS2 无线接收器通信，并把结果解析成统一的手柄状态结构。
 * 当前只关心麦轮底盘控制，因此我们主要读取：
 * 1. 左摇杆 X / Y
 * 2. 右摇杆 X
 * 3. 少量模式和档位按键
 *
 * 不做的事情：
 * - 不驱动震动电机；
 * - 不处理压力按键细节；
 * - 不和 ROS / UART 产生耦合。
 */

typedef struct
{
    bool connected;
    bool analog_mode;
    uint16_t buttons;
    uint8_t lx;
    uint8_t ly;
    uint8_t rx;
    uint8_t ry;
    uint32_t last_update_ms;
} PS2GamepadState;

/*
 * 按键位定义。
 * 这里的语义是“按下后对应位为 1”，而不是 PS2 原始协议里的低电平有效。
 */
enum
{
    PS2_BUTTON_SELECT   = (1U << 0),
    PS2_BUTTON_L3       = (1U << 1),
    PS2_BUTTON_R3       = (1U << 2),
    PS2_BUTTON_START    = (1U << 3),
    PS2_BUTTON_UP       = (1U << 4),
    PS2_BUTTON_RIGHT    = (1U << 5),
    PS2_BUTTON_DOWN     = (1U << 6),
    PS2_BUTTON_LEFT     = (1U << 7),
    PS2_BUTTON_L2       = (1U << 8),
    PS2_BUTTON_R2       = (1U << 9),
    PS2_BUTTON_L1       = (1U << 10),
    PS2_BUTTON_R1       = (1U << 11),
    PS2_BUTTON_TRIANGLE = (1U << 12),
    PS2_BUTTON_CIRCLE   = (1U << 13),
    PS2_BUTTON_CROSS    = (1U << 14),
    PS2_BUTTON_SQUARE   = (1U << 15),
};

void PS2_Gamepad_Init(void);
bool PS2_Gamepad_Poll(PS2GamepadState *out_state);
bool PS2_Gamepad_IsPressed(const PS2GamepadState *state, uint16_t button_mask);
bool PS2_Gamepad_IsFresh(const PS2GamepadState *state, uint32_t now_ms, uint32_t timeout_ms);
float PS2_Gamepad_NormalizeAxis(uint8_t raw_value, float deadband);

#ifdef __cplusplus
}
#endif

#endif /* PS2_GAMEPAD_H */
