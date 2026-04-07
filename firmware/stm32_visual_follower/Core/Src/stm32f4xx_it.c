#include "main.h"
#include "stm32f4xx_it.h"

/*
 * stm32f4xx_it.c
 *
 * 这个文件实现中断服务函数。
 * 对当前项目来说，最关键的是 USART1_IRQHandler，
 * 因为串口接收依赖 UART 中断驱动。
 */

extern UART_HandleTypeDef huart1;

void NMI_Handler(void)
{
    /* 非屏蔽中断：当前项目未做特殊处理。 */
}

void HardFault_Handler(void)
{
    /*
     * 硬 Fault 表示系统发生了严重错误，
     * 通常需要停在这里等待调试。
     */
    while (1)
    {
    }
}

void MemManage_Handler(void)
{
    while (1)
    {
    }
}

void BusFault_Handler(void)
{
    while (1)
    {
    }
}

void UsageFault_Handler(void)
{
    while (1)
    {
    }
}

void SVC_Handler(void)
{
}

void DebugMon_Handler(void)
{
}

void PendSV_Handler(void)
{
}

void SysTick_Handler(void)
{
    /*
     * 维护 HAL 的系统节拍计数。
     * HAL_Delay、HAL_GetTick 等函数都依赖这里的累加。
     */
    HAL_IncTick();
}

void USART1_IRQHandler(void)
{
    /*
     * 把 USART1 中断统一交给 HAL 层处理。
     * HAL 内部会进一步回调 HAL_UART_RxCpltCallback 等函数。
     */
    HAL_UART_IRQHandler(&huart1);
}