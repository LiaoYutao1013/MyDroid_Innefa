#ifndef __STM32F4XX_IT_H
#define __STM32F4XX_IT_H

#ifdef __cplusplus
extern "C" {
#endif

/*
 * stm32f4xx_it.h
 *
 * 这个文件声明 Cortex-M 内核异常和外设中断处理函数。
 * 其中和本项目强相关的是 USART1_IRQHandler，
 * 因为串口接收采用的是中断方式。
 */

void NMI_Handler(void);
void HardFault_Handler(void);
void MemManage_Handler(void);
void BusFault_Handler(void);
void UsageFault_Handler(void);
void SVC_Handler(void);
void DebugMon_Handler(void);
void PendSV_Handler(void);
void SysTick_Handler(void);
void USART1_IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif /* __STM32F4XX_IT_H */