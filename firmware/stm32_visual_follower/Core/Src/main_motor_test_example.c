/*
 * main_motor_test.c 片段
 *
 * 这是 main.c 中的集成示例
 * 复制这些代码到你的 main.c 中，替换原来的电机控制部分
 */

// ==================== main函数中的集成 ====================

int main(void)
{
    // 初始化阶段
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_TIM2_Init();    // 电机PWM + 编码器
    MX_TIM3_Init();    // 电机PWM + 编码器
    MX_TIM4_Init();    // 编码器
    MX_TIM5_Init();    // 编码器
    MX_USART1_UART_Init();  // 用于命令接收

    // 初始化电机测试模块
    TIM_HandleTypeDef *encoder_tims[4] = {
        &htim2,  // FL编码器
        &htim3,  // FR编码器
        &htim4,  // RL编码器
        &htim5   // RR编码器
    };
    MotorTest_Init(&htim2, encoder_tims);  // PWM用TIM2

    // 启用UART接收中断
    HAL_UART_Receive_IT(&huart1, uart_rx_buffer, 1);

    printf("Motor Test Firmware Started\r\n");
    printf("Type 'H' for command help\r\n");

    // 主循环
    uint32_t last_update = 0;
    while (1)
    {
        uint32_t now = HAL_GetTick();

        // 定期更新编码器和转速（10ms周期）
        if (now - last_update >= 10) {
            MotorTest_PeriodicUpdate();
            last_update = now;
        }

        // 低优先级背景任务
        HAL_Delay(1);
    }
}

// ==================== UART中断回调 ====================

/*
 * 在 stm32f4xx_it.c 中的 USART1_IRQHandler() 中调用此函数
 * 或配置DMA+中断接收
 */

// 单字节接收缓冲
static uint8_t uart_rx_byte = 0;

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1) {
        // 处理接收到的字节
        MotorTest_ProcessUARTByte(uart_rx_byte);

        // 立即重新启动接收（下一个字节）
        HAL_UART_Receive_IT(&huart1, &uart_rx_byte, 1);
    }
}

// ==================== 重定向 printf 到 UART ====================

// 在 main.c 顶部添加此函数，确保 printf 输出到 UART1

int fputc(int ch, FILE *f)
{
    HAL_UART_Transmit(&huart1, (uint8_t*)&ch, 1, 0xFFFF);
    return ch;
}

// ==================== 编码器TIM初始化示例 (CubeMX) ====================

/*
 * 在 CubeMX 中的配置：
 *
 * 1. TIM2 (用于FL和FR编码器)
 *    - Mode: Encoder Mode
 *    - CH1: PA0 (A相)
 *    - CH2: PA1 (B相)
 *    - Prescaler: 0
 *    - Counter Period: 65535
 *    - Auto-reload: Enabled
 *
 * 2. TIM3 (用于RL和RR编码器)
 *    - 类似配置，使用不同的GPIO
 *
 * 3. TIM2 同时配置为 PWM 输出（有些STM32可以混合）
 *    或单独使用另一个定时器输出4路PWM
 */

// 如果使用 CubeMX 的代码生成，自动生成的初始化代码会包含：
// void MX_TIM2_Init(void)
// {
//     TIM_Encoder_InitTypeDef sEncoderConfig = {0};
//     TIM_MasterConfigTypeDef sMasterConfig = {0};
//
//     htim2.Instance = TIM2;
//     htim2.Init.Prescaler = 0;
//     htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
//     htim2.Init.Period = 65535;
//     htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
//     htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
//
//     sEncoderConfig.EncoderMode = TIM_ENCODERMODE_TI12;
//     HAL_TIM_Encoder_Init(&htim2, &sEncoderConfig);
//
//     __HAL_TIM_ENABLE(&htim2);
// }

// ==================== STM32CubeIDE 项目配置 ====================

/*
 * 项目结构：
 *
 * MyDroid_Innefa/
 * ├── firmware/
 * │   └── stm32_visual_follower/
 * │       ├── Core/
 * │       │   ├── Inc/
 * │       │   │   ├── main.h
 * │       │   │   ├── motor_control.h
 * │       │   │   ├── motor_test.h          ← 新增
 * │       │   │   ├── motor_test_config.h   ← 新增
 * │       │   │   └── ...
 * │       │   └── Src/
 * │       │       ├── main.c                 (修改)
 * │       │       ├── motor_control.c
 * │       │       ├── motor_test.c           ← 新增
 * │       │       └── ...
 * │       ├── Drivers/
 * │       └── ...
 * └── ...
 *
 * CMakeLists.txt / .project 修改：
 * - 添加 Core/Src/motor_test.c 到编译列表
 * - 添加 Core/Inc 到包含路径（通常已添加）
 */

// ==================== 编译命令示例 ====================

/*
 # 使用 arm-gcc 直接编译
 arm-none-eabi-gcc \
    -mcpu=cortex-m4 \
    -mthumb \
    -mfpu=fpv4-sp-d16 \
    -mfloat-abi=hard \
    -O2 \
    -Wall \
    -ICore/Inc \
    -IDrivers/STM32F4xx_HAL_Driver/Inc \
    -DSTM32F407xx \
    Core/Src/main.c \
    Core/Src/motor_test.c \
    Core/Src/motor_control.c \
    ... \
    -o firmware.elf

 # 使用 STM32CubeIDE (GUI)
 # 项目右键 → Build Project
 */

// ==================== 集成检查清单 ====================

/*
 编译前检查：
 ✓ motor_test.h 已添加到 Core/Inc/
 ✓ motor_test.c 已添加到 Core/Src/
 ✓ motor_test_config.h 中的 GPIO 配置与硬件一致
 ✓ main.c 中已调用 MotorTest_Init()
 ✓ UART1 初始化并启用接收中断
 ✓ TIM2/TIM3 配置为 PWM 输出和 QEI 编码器输入
 ✓ printf 已重定向到 UART1
 ✓ 所有编码器 TIM 已初始化

 烧录后检查：
 ✓ UART 终端可收到 "Motor Test Firmware Started"
 ✓ 输入 'H' 后收到帮助信息
 ✓ 输入 'M 0 100' 后前左轮缓慢转动
 ✓ 输入 'E 0' 后收到编码器数据
 */
