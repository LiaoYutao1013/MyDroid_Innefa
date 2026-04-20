#include "ps2_gamepad.h"
#include "app_config.h"

#include <math.h>
#include <string.h>

/*
 * ps2_gamepad.c
 *
 * 当前采用“软件时序 SPI”读取 PS2 无线接收器。
 * 这么做的主要原因是：
 * 1. 当前 CubeMX 工程还没有为 PS2 接收器分配额外 SPI 外设；
 * 2. PC0~PC3 是当前未占用引脚，直接用 GPIO 最容易接线和验证；
 * 3. 对 PS2 手柄这种低速外设，软件时序完全够用。
 */

#define PS2_MODE_DIGITAL                    0x41U
#define PS2_MODE_ANALOG_RED                 0x73U
#define PS2_MODE_ANALOG_PRESSURE            0x79U

static uint32_t s_cycles_per_us = 0U;
static uint32_t s_last_config_attempt_ms = 0U;

static void PS2_Gamepad_EnableCycleCounter(void)
{
    /*
     * 利用 DWT->CYCCNT 实现微秒级忙等待。
     * 这比手写空循环更稳定，也更不受编译优化影响。
     */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    DWT->CYCCNT = 0U;
    s_cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000U;
}

static void PS2_Gamepad_DelayUs(uint32_t delay_us)
{
    uint32_t start_cycles;
    uint32_t target_cycles;

    if (s_cycles_per_us == 0U)
    {
        PS2_Gamepad_EnableCycleCounter();
    }

    start_cycles = DWT->CYCCNT;
    target_cycles = delay_us * s_cycles_per_us;
    while ((DWT->CYCCNT - start_cycles) < target_cycles)
    {
    }
}

static void PS2_Gamepad_GpioInit(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOC_CLK_ENABLE();

    /*
     * 默认空闲状态：
     * - ATT 高
     * - CMD 高
     * - CLK 高
     */
    HAL_GPIO_WritePin(PS2_ATT_GPIO_Port, PS2_ATT_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(PS2_CMD_GPIO_Port, PS2_CMD_Pin, GPIO_PIN_SET);
    HAL_GPIO_WritePin(PS2_CLK_GPIO_Port, PS2_CLK_Pin, GPIO_PIN_SET);

    GPIO_InitStruct.Pin = PS2_ATT_Pin | PS2_CMD_Pin | PS2_CLK_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = PS2_DAT_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(PS2_DAT_GPIO_Port, &GPIO_InitStruct);
}

static uint8_t PS2_Gamepad_TransferByte(uint8_t tx_byte)
{
    uint8_t bit_index;
    uint8_t rx_byte = 0U;

    /*
     * PS2 协议按 LSB first 发送。
     * 每个 bit 的流程是：
     * 1. 先准备 CMD 数据；
     * 2. 拉低 CLK；
     * 3. 读取 DAT；
     * 4. 拉高 CLK，进入下一 bit。
     */
    for (bit_index = 0U; bit_index < 8U; ++bit_index)
    {
        HAL_GPIO_WritePin(
            PS2_CMD_GPIO_Port,
            PS2_CMD_Pin,
            ((tx_byte >> bit_index) & 0x01U) != 0U ? GPIO_PIN_SET : GPIO_PIN_RESET);

        PS2_Gamepad_DelayUs(PS2_GAMEPAD_CLOCK_DELAY_US);
        HAL_GPIO_WritePin(PS2_CLK_GPIO_Port, PS2_CLK_Pin, GPIO_PIN_RESET);
        PS2_Gamepad_DelayUs(PS2_GAMEPAD_CLOCK_DELAY_US);

        if (HAL_GPIO_ReadPin(PS2_DAT_GPIO_Port, PS2_DAT_Pin) == GPIO_PIN_SET)
        {
            rx_byte |= (uint8_t)(1U << bit_index);
        }

        HAL_GPIO_WritePin(PS2_CLK_GPIO_Port, PS2_CLK_Pin, GPIO_PIN_SET);
        PS2_Gamepad_DelayUs(PS2_GAMEPAD_CLOCK_DELAY_US);
    }

    return rx_byte;
}

static void PS2_Gamepad_TransferPacket(const uint8_t *tx_data, uint8_t *rx_data, uint8_t length)
{
    uint8_t index;

    HAL_GPIO_WritePin(PS2_ATT_GPIO_Port, PS2_ATT_Pin, GPIO_PIN_RESET);
    PS2_Gamepad_DelayUs(PS2_GAMEPAD_CLOCK_DELAY_US * 2U);

    for (index = 0U; index < length; ++index)
    {
        const uint8_t tx_byte = (tx_data != NULL) ? tx_data[index] : 0x00U;
        const uint8_t rx_byte = PS2_Gamepad_TransferByte(tx_byte);
        if (rx_data != NULL)
        {
            rx_data[index] = rx_byte;
        }
    }

    HAL_GPIO_WritePin(PS2_ATT_GPIO_Port, PS2_ATT_Pin, GPIO_PIN_SET);
    PS2_Gamepad_DelayUs(PS2_GAMEPAD_CLOCK_DELAY_US * 4U);
}

static bool PS2_Gamepad_SendCommand(const uint8_t *tx_data, uint8_t *rx_data, uint8_t length)
{
    PS2_Gamepad_TransferPacket(tx_data, rx_data, length);
    return (rx_data != NULL) && (length >= 3U) && (rx_data[2] == 0x5AU);
}

static bool PS2_Gamepad_TryEnableAnalogMode(void)
{
    uint8_t rx_buffer[9];

    static const uint8_t enter_config_cmd[5] = {0x01U, 0x43U, 0x00U, 0x01U, 0x00U};
    static const uint8_t set_analog_cmd[9] = {0x01U, 0x44U, 0x00U, 0x01U, 0x03U, 0x00U, 0x00U, 0x00U, 0x00U};
    static const uint8_t exit_config_cmd[9] = {0x01U, 0x43U, 0x00U, 0x00U, 0x5AU, 0x5AU, 0x5AU, 0x5AU, 0x5AU};
    static const uint8_t read_data_cmd[9] = {0x01U, 0x42U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U};

    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (!PS2_Gamepad_SendCommand(enter_config_cmd, rx_buffer, 5U))
    {
        return false;
    }

    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (!PS2_Gamepad_SendCommand(set_analog_cmd, rx_buffer, 9U))
    {
        return false;
    }

    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (!PS2_Gamepad_SendCommand(exit_config_cmd, rx_buffer, 9U))
    {
        return false;
    }

    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (!PS2_Gamepad_SendCommand(read_data_cmd, rx_buffer, 9U))
    {
        return false;
    }

    return (rx_buffer[1] == PS2_MODE_ANALOG_RED) || (rx_buffer[1] == PS2_MODE_ANALOG_PRESSURE);
}

void PS2_Gamepad_Init(void)
{
    PS2_Gamepad_GpioInit();
    PS2_Gamepad_EnableCycleCounter();

    /*
     * 上电后先尝试切一次模拟模式。
     * 即便当前接收器没插、手柄没配对，也不视为错误，后续 Poll 时还会继续重试。
     */
    s_last_config_attempt_ms = HAL_GetTick();
    (void)PS2_Gamepad_TryEnableAnalogMode();
}

bool PS2_Gamepad_Poll(PS2GamepadState *out_state)
{
    uint8_t rx_buffer[9];
    const uint32_t now_ms = HAL_GetTick();
    static const uint8_t read_data_cmd[9] = {0x01U, 0x42U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U, 0x00U};

    if (out_state == NULL)
    {
        return false;
    }

    memset(rx_buffer, 0, sizeof(rx_buffer));
    if (!PS2_Gamepad_SendCommand(read_data_cmd, rx_buffer, 9U))
    {
        memset(out_state, 0, sizeof(*out_state));
        return false;
    }

    if ((rx_buffer[1] != PS2_MODE_ANALOG_RED) && (rx_buffer[1] != PS2_MODE_ANALOG_PRESSURE))
    {
        out_state->connected = (rx_buffer[1] == PS2_MODE_DIGITAL);
        out_state->analog_mode = false;
        out_state->buttons = 0U;
        out_state->lx = 0x80U;
        out_state->ly = 0x80U;
        out_state->rx = 0x80U;
        out_state->ry = 0x80U;
        out_state->last_update_ms = 0U;

        /*
         * 接收器在线但尚未进入模拟模式时，隔一段时间自动重试。
         * 这样用户无需每次都重新上电配对。
         */
        if ((now_ms - s_last_config_attempt_ms) >= 1000U)
        {
            s_last_config_attempt_ms = now_ms;
            (void)PS2_Gamepad_TryEnableAnalogMode();
        }
        return false;
    }

    out_state->connected = true;
    out_state->analog_mode = true;
    out_state->buttons = (uint16_t)(~((uint16_t)rx_buffer[3] | ((uint16_t)rx_buffer[4] << 8U)));
    out_state->rx = rx_buffer[5];
    out_state->ry = rx_buffer[6];
    out_state->lx = rx_buffer[7];
    out_state->ly = rx_buffer[8];
    out_state->last_update_ms = now_ms;
    return true;
}

bool PS2_Gamepad_IsPressed(const PS2GamepadState *state, uint16_t button_mask)
{
    if (state == NULL)
    {
        return false;
    }

    return (state->buttons & button_mask) != 0U;
}

bool PS2_Gamepad_IsFresh(const PS2GamepadState *state, uint32_t now_ms, uint32_t timeout_ms)
{
    if ((state == NULL) || (state->last_update_ms == 0U))
    {
        return false;
    }

    return (now_ms - state->last_update_ms) <= timeout_ms;
}

float PS2_Gamepad_NormalizeAxis(uint8_t raw_value, float deadband)
{
    float normalized;

    /*
     * PS2 摇杆原始值范围通常为 0~255，中位约为 128。
     * 这里统一映射到 -1.0 ~ 1.0，方便后续直接乘以目标速度上限。
     */
    normalized = ((float)raw_value - 128.0f) / 127.0f;
    if (normalized > 1.0f)
    {
        normalized = 1.0f;
    }
    if (normalized < -1.0f)
    {
        normalized = -1.0f;
    }

    if (fabsf(normalized) <= deadband)
    {
        return 0.0f;
    }

    /*
     * 除死区后重新拉伸，避免摇杆刚离开中位时控制太“肉”。
     */
    if (normalized > 0.0f)
    {
        return (normalized - deadband) / (1.0f - deadband);
    }
    return (normalized + deadband) / (1.0f - deadband);
}
