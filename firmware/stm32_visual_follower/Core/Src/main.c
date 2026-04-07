#include "main.h"
#include "motor_control.h"
#include "protocol.h"

/*
 * main.c
 *
 * 这是 STM32 固件的主入口文件。
 * 主要职责：
 * 1. 初始化时钟、GPIO、UART、PWM 定时器。
 * 2. 启动 UART 接收中断。
 * 3. 在主循环里根据最近一次解析到的命令控制底盘和 Pan 云台。
 * 4. 实现超时保护：超过 500 ms 未收到新命令时，停车并让云台回中。
 */

UART_HandleTypeDef huart1;
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim4;

/* 串口中断一次只接收 1 个字节，因此需要一个单字节缓冲。 */
static uint8_t g_uart_rx_byte = 0U;

/* 是否至少收过一条完整有效命令。 */
static volatile uint8_t g_command_received = 0U;

/* 最近一次成功解析命令的时间戳。 */
static volatile uint32_t g_last_command_ms = 0U;

/* 最近一次成功解析出的完整命令。 */
static RobotCommand g_latest_command = {0};

static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);

int main(void)
{
    /* HAL 库初始化。 */
    HAL_Init();

    /* 配置系统时钟。 */
    SystemClock_Config();

    /* 初始化底层外设。 */
    MX_GPIO_Init();
    MX_USART1_UART_Init();
    MX_TIM3_Init();
    MX_TIM4_Init();

    /* 初始化协议解析器和执行层控制模块。 */
    Protocol_Init();
    MotorControl_Init(&htim3, &htim4);

    /* 启动串口中断接收。 */
    if (HAL_UART_Receive_IT(&huart1, &g_uart_rx_byte, 1U) != HAL_OK)
    {
        Error_Handler();
    }

    for (;;)
    {
        RobotCommand command_snapshot;
        uint8_t have_command;
        uint32_t last_command_ms;
        const uint32_t now_ms = HAL_GetTick();

        /*
         * 为了避免中断回调正在更新命令结构体，
         * 这里先在临界区里拷贝一份快照出来。
         */
        __disable_irq();
        command_snapshot = g_latest_command;
        have_command = g_command_received;
        last_command_ms = g_last_command_ms;
        __enable_irq();

        if (have_command != 0U)
        {
            /*
             * 安全策略：
             * 1. 超过 500 ms 未收到新指令，底盘立即停车。
             * 2. Pan 云台自动回到中位，避免长时间停在极限位置。
             * 3. 收到急停或无效指令时，同样执行上述保护。
             */
            if (((now_ms - last_command_ms) > UART_COMMAND_TIMEOUT_MS) ||
                (!command_snapshot.command_valid) ||
                command_snapshot.estop)
            {
                MotorControl_StopAll();
                gimbal_pan_control(PAN_SERVO_NEUTRAL_DEG);
            }
            else
            {
                /*
                 * 命令有效时：
                 * 1. 先控制 Pan 云台角度。
                 * 2. 再控制麦轮底盘速度。
                 */
                gimbal_pan_control(command_snapshot.pan_angle_deg);
                MotorControl_SetBodyVelocity(
                    command_snapshot.vx_mps,
                    command_snapshot.vy_mps,
                    command_snapshot.omega_radps);
            }
        }
        else
        {
            /* 系统上电后，在未收到任何有效命令之前保持安全静止状态。 */
            MotorControl_StopAll();
            gimbal_pan_control(PAN_SERVO_NEUTRAL_DEG);
        }

        /*
         * 主循环不需要跑得太快，
         * 这里做一个很小的延时，降低空转负担。
         */
        HAL_Delay(2U);
    }
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        RobotCommand parsed_command;

        /*
         * 每收到 1 个字节，就交给协议解析器累积。
         * 只有当完整一帧成功解析并通过 CRC 时，才会返回 true。
         */
        if (Protocol_ProcessByte(g_uart_rx_byte, &parsed_command, HAL_GetTick()))
        {
            g_latest_command = parsed_command;
            g_command_received = 1U;
            g_last_command_ms = parsed_command.last_update_ms;
        }

        /* 继续启动下一字节接收，形成持续不断的字节流处理。 */
        if (HAL_UART_Receive_IT(&huart1, &g_uart_rx_byte, 1U) != HAL_OK)
        {
            Error_Handler();
        }
    }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == USART1)
    {
        /*
         * 出现串口错误时，先终止接收，再重新启动接收。
         * 这样可以提高现场通信时的鲁棒性。
         */
        HAL_UART_AbortReceive(huart);
        if (HAL_UART_Receive_IT(&huart1, &g_uart_rx_byte, 1U) != HAL_OK)
        {
            Error_Handler();
        }
    }
}

void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE2);

    /*
     * 使用 HSI + PLL 生成系统时钟。
     * 这套配置对 STM32F407 是比较常见的一组参数。
     */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    RCC_OscInitStruct.HSIState = RCC_HSI_ON;
    RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
    RCC_OscInitStruct.PLL.PLLM = 16;
    RCC_OscInitStruct.PLL.PLLN = 336;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV4;
    RCC_OscInitStruct.PLL.PLLQ = 7;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
    {
        Error_Handler();
    }

    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                                  RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
    {
        Error_Handler();
    }
}

static void MX_TIM3_Init(void)
{
    TIM_MasterConfigTypeDef sMasterConfig = {0};
    TIM_OC_InitTypeDef sConfigOC = {0};

    __HAL_RCC_TIM3_CLK_ENABLE();

    /*
     * TIM3 用于 4 路底盘电机 PWM。
     * Prescaler=83 时，在 84 MHz 时钟下可得到 1 MHz 计数频率。
     * ARR=MOTOR_PWM_PERIOD_COUNTS=49，则 PWM 频率约为 20 kHz。
     */
    htim3.Instance = TIM3;
    htim3.Init.Prescaler = 83;
    htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim3.Init.Period = MOTOR_PWM_PERIOD_COUNTS;
    htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
    {
        Error_Handler();
    }

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
    {
        Error_Handler();
    }

    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = 0;
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;

    if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK) { Error_Handler(); }
    if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2) != HAL_OK) { Error_Handler(); }
    if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_3) != HAL_OK) { Error_Handler(); }
    if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_4) != HAL_OK) { Error_Handler(); }
}

static void MX_TIM4_Init(void)
{
    TIM_MasterConfigTypeDef sMasterConfig = {0};
    TIM_OC_InitTypeDef sConfigOC = {0};

    __HAL_RCC_TIM4_CLK_ENABLE();

    /*
     * TIM4 用于 Pan 舵机 PWM。
     * Prescaler=83 -> 1 MHz 计数频率。
     * ARR=19999 -> 周期 20 ms，即 50 Hz。
     */
    htim4.Instance = TIM4;
    htim4.Init.Prescaler = 83;
    htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim4.Init.Period = (PAN_SERVO_PWM_PERIOD_US - 1U);
    htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    if (HAL_TIM_PWM_Init(&htim4) != HAL_OK)
    {
        Error_Handler();
    }

    sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
    sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
    if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
    {
        Error_Handler();
    }

    /* 上电默认脉宽 1500 us，对应大多数舵机中位附近。 */
    sConfigOC.OCMode = TIM_OCMODE_PWM1;
    sConfigOC.Pulse = 1500;
    sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
    sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;

    if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, PAN_SERVO_CHANNEL) != HAL_OK)
    {
        Error_Handler();
    }
}

static void MX_USART1_UART_Init(void)
{
    __HAL_RCC_USART1_CLK_ENABLE();

    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
        Error_Handler();
    }

    /* 开启 USART1 中断。 */
    HAL_NVIC_SetPriority(USART1_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
}

static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    /* 上电默认先关闭所有方向输出和驱动待机脚。 */
    HAL_GPIO_WritePin(GPIOC, FL_IN1_Pin | FL_IN2_Pin | FR_IN1_Pin | FR_IN2_Pin | RL_IN1_Pin | RL_IN2_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(GPIOB, RR_IN1_Pin | RR_IN2_Pin, GPIO_PIN_RESET);
    HAL_GPIO_WritePin(MOTOR_STBY_GPIO_Port, MOTOR_STBY_Pin, GPIO_PIN_RESET);

    /* 方向控制脚配置为推挽输出。 */
    GPIO_InitStruct.Pin = FL_IN1_Pin | FL_IN2_Pin | FR_IN1_Pin | FR_IN2_Pin | RL_IN1_Pin | RL_IN2_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = RR_IN1_Pin | RR_IN2_Pin | MOTOR_STBY_Pin;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* TIM3 PWM 引脚配置。 */
    GPIO_InitStruct.Pin = FL_PWM_Pin | FR_PWM_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = RL_PWM_Pin | RR_PWM_Pin;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* TIM4 Pan 舵机 PWM 引脚配置。 */
    GPIO_InitStruct.Pin = PAN_SERVO_Pin;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM4;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* USART1 引脚配置。 */
    GPIO_InitStruct.Pin = ROCK_UART_TX_Pin | ROCK_UART_RX_Pin;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
}

void Error_Handler(void)
{
    /*
     * 错误处理策略：
     * 1. 关闭中断，避免系统继续执行不确定逻辑。
     * 2. 停止底盘电机。
     * 3. 让云台回到中位。
     * 4. 进入死循环等待调试。
     */
    __disable_irq();
    MotorControl_StopAll();
    gimbal_pan_control(PAN_SERVO_NEUTRAL_DEG);
    for (;;)
    {
    }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    (void)file;
    (void)line;
}
#endif