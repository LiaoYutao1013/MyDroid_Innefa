/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdbool.h>
#include <string.h>

#include "motor_control.h"
#include "ps2_gamepad.h"
#include "protocol.h"

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim2;
TIM_HandleTypeDef htim3;
TIM_HandleTypeDef htim4;
TIM_HandleTypeDef htim5;
TIM_HandleTypeDef htim8;

UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
static uint8_t g_uart1_rx_byte = 0U;
static volatile uint8_t g_has_command = 0U;
static RobotCommand g_latest_command;
static PS2GamepadState g_ps2_state;
static uint8_t g_ps2_manual_enabled = 0U;
static uint8_t g_ps2_estop_latched = 0U;
static uint8_t g_ps2_start_prev = 0U;
static uint8_t g_ps2_select_prev = 0U;
static uint32_t g_ps2_last_poll_ms = 0U;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_TIM1_Init(void);
static void MX_TIM2_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);
static void MX_TIM5_Init(void);
static void MX_TIM8_Init(void);
static void MX_USART1_UART_Init(void);
void HAL_TIM_MspPostInit(TIM_HandleTypeDef *htim);
/* USER CODE BEGIN PFP */
static void App_EnableUsart1Interrupt(void);
static void App_StartUart1Receive(void);
static bool App_CopyLatestCommand(RobotCommand *out_command);
static bool App_CommandTimedOut(const RobotCommand *command, uint32_t now_ms);
static void App_PollPs2Gamepad(uint32_t now_ms);
static void App_UpdatePs2ModeState(const PS2GamepadState *state);
static bool App_GetPs2DriveCommand(float *vx_mps, float *vy_mps, float *omega_radps);
static bool App_HandlePs2Bypass(uint32_t now_ms);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void App_EnableUsart1Interrupt(void)
{
  /*
   * CubeMX 当前已经生成了 USART1_IRQHandler，
   * 但没有自动在 NVIC 中打开该中断，这里在应用层显式补齐。
   */
  HAL_NVIC_SetPriority(USART1_IRQn, 1U, 0U);
  HAL_NVIC_EnableIRQ(USART1_IRQn);
}

static void App_StartUart1Receive(void)
{
  /*
   * 串口接收采用“单字节中断 + 协议状态机拼帧”。
   * 这样可以在存在噪声字节时继续通过帧头重新同步，
   * 是当前阶段最稳妥、最容易维护的下位机接收方式。
   */
  if (HAL_UART_Receive_IT(&huart1, &g_uart1_rx_byte, 1U) != HAL_OK)
  {
    Error_Handler();
  }
}

static bool App_CopyLatestCommand(RobotCommand *out_command)
{
  bool has_command = false;
  uint32_t primask;

  if (out_command == NULL)
  {
    return false;
  }

  primask = __get_PRIMASK();
  __disable_irq();
  if (g_has_command != 0U)
  {
    *out_command = g_latest_command;
    has_command = true;
  }
  if (primask == 0U)
  {
    __enable_irq();
  }

  return has_command;
}

static bool App_CommandTimedOut(const RobotCommand *command, uint32_t now_ms)
{
  if (command == NULL)
  {
    return true;
  }

  return (now_ms - command->last_update_ms) > UART_COMMAND_TIMEOUT_MS;
}

static void App_PollPs2Gamepad(uint32_t now_ms)
{
  if ((now_ms - g_ps2_last_poll_ms) < PS2_GAMEPAD_POLL_INTERVAL_MS)
  {
    return;
  }

  g_ps2_last_poll_ms = now_ms;
  if (PS2_Gamepad_Poll(&g_ps2_state))
  {
    App_UpdatePs2ModeState(&g_ps2_state);
  }
  else
  {
    /*
     * 如果当前轮询没读到有效帧，就清掉边沿检测状态，避免后续“补读到一帧”时误判按钮连击。
     * 是否真正视为掉线，由超时逻辑统一判断。
     */
    g_ps2_start_prev = 0U;
    g_ps2_select_prev = 0U;
  }
}

static void App_UpdatePs2ModeState(const PS2GamepadState *state)
{
  uint8_t start_pressed;
  uint8_t select_pressed;

  if (state == NULL)
  {
    return;
  }

  start_pressed = PS2_Gamepad_IsPressed(state, PS2_BUTTON_START) ? 1U : 0U;
  select_pressed = PS2_Gamepad_IsPressed(state, PS2_BUTTON_SELECT) ? 1U : 0U;

  /*
   * SELECT：急停并退出旁路模式。
   * 这样用户在本地手柄控制时，也能在 STM32 这一层直接切断底盘输出。
   */
  if ((select_pressed != 0U) && (g_ps2_select_prev == 0U))
  {
    g_ps2_estop_latched = 1U;
    g_ps2_manual_enabled = 0U;
  }

  /*
   * START：切换旁路模式。
   * 如果之前因为 SELECT 急停而锁死，按一次 START 会先解除急停，再进入旁路模式。
   */
  if ((start_pressed != 0U) && (g_ps2_start_prev == 0U))
  {
    g_ps2_estop_latched = 0U;
    g_ps2_manual_enabled = (g_ps2_manual_enabled == 0U) ? 1U : 0U;
  }

  g_ps2_start_prev = start_pressed;
  g_ps2_select_prev = select_pressed;
}

static bool App_GetPs2DriveCommand(float *vx_mps, float *vy_mps, float *omega_radps)
{
  float forward;
  float strafe;
  float rotate;
  float speed_scale = PS2_GAMEPAD_NORMAL_SCALE;

  if ((vx_mps == NULL) || (vy_mps == NULL) || (omega_radps == NULL))
  {
    return false;
  }

  if ((!g_ps2_state.connected) || (!g_ps2_state.analog_mode))
  {
    return false;
  }

  /*
   * 轴映射约定：
   * - 左摇杆 Y：前进 / 后退
   * - 左摇杆 X：左右平移
   * - 右摇杆 X：原地旋转
   *
   * 由于 PS2 原始值中“向上/向左”通常对应更小的数值，
   * 所以下面会根据车体坐标系再做一次符号调整。
   */
  forward = -PS2_Gamepad_NormalizeAxis(g_ps2_state.ly, PS2_GAMEPAD_AXIS_DEADBAND);
  strafe = -PS2_Gamepad_NormalizeAxis(g_ps2_state.lx, PS2_GAMEPAD_AXIS_DEADBAND);
  rotate = -PS2_Gamepad_NormalizeAxis(g_ps2_state.rx, PS2_GAMEPAD_AXIS_DEADBAND);

  /*
   * L1 / R1 做速度档位切换：
   * - L1：慢速精调
   * - 默认：普通调试速度
   * - R1：全速
   */
  if (PS2_Gamepad_IsPressed(&g_ps2_state, PS2_BUTTON_L1))
  {
    speed_scale = PS2_GAMEPAD_SLOW_SCALE;
  }
  else if (PS2_Gamepad_IsPressed(&g_ps2_state, PS2_BUTTON_R1))
  {
    speed_scale = PS2_GAMEPAD_FAST_SCALE;
  }

  *vx_mps = forward * MAX_BODY_VX_MPS * speed_scale;
  *vy_mps = strafe * MAX_BODY_VY_MPS * speed_scale;
  *omega_radps = rotate * MAX_BODY_OMEGA_RADPS * speed_scale;
  return true;
}

static bool App_HandlePs2Bypass(uint32_t now_ms)
{
  float vx_mps;
  float vy_mps;
  float omega_radps;

  App_PollPs2Gamepad(now_ms);

  /*
   * 只有在两种情况下，PS2 旁路链路才会“抢占”UART：
   * 1. 用户明确按 START 进入了旁路模式；
   * 2. 用户按 SELECT 触发了本地急停，需要由 STM32 本地保持停车。
   */
  if ((g_ps2_manual_enabled == 0U) && (g_ps2_estop_latched == 0U))
  {
    return false;
  }

  /*
   * 只要本地急停锁存、手柄超时或接收器失联，就直接停车。
   * 注意这里不会自动切回 UART，目的是防止用户以为自己在本地控车，
   * 但实际上又被 Radxa 的旧命令接管。
   */
  if ((g_ps2_estop_latched != 0U) ||
      (!PS2_Gamepad_IsFresh(&g_ps2_state, now_ms, PS2_GAMEPAD_TIMEOUT_MS)) ||
      (!g_ps2_state.connected) ||
      (!g_ps2_state.analog_mode))
  {
    MotorControl_StopAll();
    return true;
  }

  if (!App_GetPs2DriveCommand(&vx_mps, &vy_mps, &omega_radps))
  {
    MotorControl_StopAll();
    return true;
  }

  MotorControl_SetBodyVelocity(vx_mps, vy_mps, omega_radps);
  return true;
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_TIM1_Init();
  MX_TIM2_Init();
  MX_TIM3_Init();
  MX_TIM4_Init();
  MX_TIM5_Init();
  MX_TIM8_Init();
  MX_USART1_UART_Init();
  /* USER CODE BEGIN 2 */
  /*
   * 先清空上一轮状态，确保系统上电时不会沿用未知命令。
   */
  memset(&g_latest_command, 0, sizeof(g_latest_command));
  g_latest_command.pan_angle_deg = PAN_SERVO_NEUTRAL_DEG;
  memset(&g_ps2_state, 0, sizeof(g_ps2_state));
  Protocol_Init();

  /*
   * 当前阶段只初始化麦轮控制：
   * - TIM1 驱动前轴两轮；
   * - TIM4 驱动后轴两轮；
   * - 不初始化 Pan/云台硬件输出。
   */
  MotorControl_Init(&htim1, &htim4);

  /*
   * 初始化 PS2 手柄直连旁路控制。
   * 默认不会自动接管底盘，必须由用户在手柄上按 START 才进入旁路模式。
   */
  PS2_Gamepad_Init();

  /*
   * 打开 USART1 中断，并立即挂起第一字节接收。
   * 从这一刻开始，ROCK 3B 发来的控制帧才会真正进入协议解析链路。
   */
  App_EnableUsart1Interrupt();
  App_StartUart1Receive();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    RobotCommand command_snapshot;
    const uint32_t now_ms = HAL_GetTick();
    const bool has_command = App_CopyLatestCommand(&command_snapshot);

    /*
     * 优先处理 PS2 本地旁路控制。
     * 一旦旁路模式被用户显式开启，STM32 会优先服从本地手柄。
     */
    if (App_HandlePs2Bypass(now_ms))
    {
      HAL_Delay(5);
      continue;
    }

    /*
     * 只有满足下面 4 个条件时才允许驱动底盘：
     * 1. 已经至少收到过一帧完整合法命令；
     * 2. 该命令没有超时；
     * 3. 上位机明确标记该命令有效；
     * 4. 当前不处于急停状态。
     *
     * 任何一个条件不满足，都直接停车进入保护。
     */
    if ((!has_command) ||
        App_CommandTimedOut(&command_snapshot, now_ms) ||
        (!command_snapshot.command_valid) ||
        command_snapshot.estop)
    {
      MotorControl_StopAll();
    }
    else
    {
      MotorControl_ApplyCommand(&command_snapshot);
    }

    /*
     * 短延时用于避免主循环空转占满 CPU。
     * 控制实时性主要由串口中断、协议解析和超时保护保证。
     */
    HAL_Delay(5);
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};
  TIM_BreakDeadTimeConfigTypeDef sBreakDeadTimeConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 83;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 999;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_PWM_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCNPolarity = TIM_OCNPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  sConfigOC.OCIdleState = TIM_OCIDLESTATE_RESET;
  sConfigOC.OCNIdleState = TIM_OCNIDLESTATE_RESET;
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim1, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  sBreakDeadTimeConfig.OffStateRunMode = TIM_OSSR_DISABLE;
  sBreakDeadTimeConfig.OffStateIDLEMode = TIM_OSSI_DISABLE;
  sBreakDeadTimeConfig.LockLevel = TIM_LOCKLEVEL_OFF;
  sBreakDeadTimeConfig.DeadTime = 0;
  sBreakDeadTimeConfig.BreakState = TIM_BREAK_DISABLE;
  sBreakDeadTimeConfig.BreakPolarity = TIM_BREAKPOLARITY_HIGH;
  sBreakDeadTimeConfig.AutomaticOutput = TIM_AUTOMATICOUTPUT_DISABLE;
  if (HAL_TIMEx_ConfigBreakDeadTime(&htim1, &sBreakDeadTimeConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */
  HAL_TIM_MspPostInit(&htim1);

}

/**
  * @brief TIM2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM2_Init(void)
{

  /* USER CODE BEGIN TIM2_Init 0 */

  /* USER CODE END TIM2_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM2_Init 1 */

  /* USER CODE END TIM2_Init 1 */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 0;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 4294967295;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI1;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 0;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 0;
  if (HAL_TIM_Encoder_Init(&htim2, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim2, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM2_Init 2 */

  /* USER CODE END TIM2_Init 2 */

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 0;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 65535;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 0;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 0;
  if (HAL_TIM_Encoder_Init(&htim3, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */

}

/**
  * @brief TIM4 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM4_Init(void)
{

  /* USER CODE BEGIN TIM4_Init 0 */

  /* USER CODE END TIM4_Init 0 */

  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  /* USER CODE BEGIN TIM4_Init 1 */

  /* USER CODE END TIM4_Init 1 */
  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 83;
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 999;
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
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_4) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM4_Init 2 */

  /* USER CODE END TIM4_Init 2 */
  HAL_TIM_MspPostInit(&htim4);

}

/**
  * @brief TIM5 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM5_Init(void)
{

  /* USER CODE BEGIN TIM5_Init 0 */

  /* USER CODE END TIM5_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM5_Init 1 */

  /* USER CODE END TIM5_Init 1 */
  htim5.Instance = TIM5;
  htim5.Init.Prescaler = 0;
  htim5.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim5.Init.Period = 65535;
  htim5.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim5.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 0;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 0;
  if (HAL_TIM_Encoder_Init(&htim5, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim5, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM5_Init 2 */

  /* USER CODE END TIM5_Init 2 */

}

/**
  * @brief TIM8 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM8_Init(void)
{

  /* USER CODE BEGIN TIM8_Init 0 */

  /* USER CODE END TIM8_Init 0 */

  TIM_Encoder_InitTypeDef sConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM8_Init 1 */

  /* USER CODE END TIM8_Init 1 */
  htim8.Instance = TIM8;
  htim8.Init.Prescaler = 0;
  htim8.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim8.Init.Period = 65535;
  htim8.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim8.Init.RepetitionCounter = 0;
  htim8.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  sConfig.EncoderMode = TIM_ENCODERMODE_TI12;
  sConfig.IC1Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC1Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC1Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC1Filter = 0;
  sConfig.IC2Polarity = TIM_ICPOLARITY_RISING;
  sConfig.IC2Selection = TIM_ICSELECTION_DIRECTTI;
  sConfig.IC2Prescaler = TIM_ICPSC_DIV1;
  sConfig.IC2Filter = 0;
  if (HAL_TIM_Encoder_Init(&htim8, &sConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim8, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM8_Init 2 */

  /* USER CODE END TIM8_Init 2 */

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
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
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, GPIO_PIN_10|GPIO_PIN_11|GPIO_PIN_12|GPIO_PIN_13
                          |GPIO_PIN_4|GPIO_PIN_7|GPIO_PIN_8, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, GPIO_PIN_12, GPIO_PIN_RESET);

  /*Configure GPIO pins : PB10 PB11 PB12 PB13
                           PB4 PB7 PB8 */
  GPIO_InitStruct.Pin = GPIO_PIN_10|GPIO_PIN_11|GPIO_PIN_12|GPIO_PIN_13
                          |GPIO_PIN_4|GPIO_PIN_7|GPIO_PIN_8;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pin : PA12 */
  GPIO_InitStruct.Pin = GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if ((huart == NULL) || (huart->Instance != USART1))
  {
    return;
  }

  /*
   * 每收到 1 个字节，都立即送入协议状态机。
   * 当状态机确认已经拼出完整控制帧后，再原子性更新“最新命令快照”。
   */
  RobotCommand parsed_command;
  if (Protocol_ProcessByte(g_uart1_rx_byte, &parsed_command, HAL_GetTick()))
  {
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    g_latest_command = parsed_command;
    g_has_command = 1U;
    if (primask == 0U)
    {
      __enable_irq();
    }
  }

  App_StartUart1Receive();
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
  if ((huart == NULL) || (huart->Instance != USART1))
  {
    return;
  }

  /*
   * 一旦出现串口硬件错误，就清标志并重新挂起接收。
   * 这样可以尽快从噪声、溢出等异常中恢复，不把错误状态带到下一帧。
   */
  __HAL_UART_CLEAR_PEFLAG(huart);
  __HAL_UART_CLEAR_FEFLAG(huart);
  __HAL_UART_CLEAR_NEFLAG(huart);
  __HAL_UART_CLEAR_OREFLAG(huart);
  (void)HAL_UART_AbortReceive(huart);
  App_StartUart1Receive();
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
