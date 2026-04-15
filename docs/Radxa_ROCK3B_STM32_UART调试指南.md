# Radxa ROCK 3B 与 STM32 串口调试指南（VOFA+ 验证）

本指南说明如何使用电脑上的串口调试器 VOFA+，对 Radxa ROCK 3B 与 STM32 之间的 UART 串口通信进行调试与验证。配合 `tools/uart_debug_tool.py` 进行测试，可快速确认串口链路是否正常。

---

## 1. 目标

- 验证 Radxa ROCK 3B 与 STM32 之间的 UART 串口链路
- 通过 VOFA+ 同时观察两端串口数据
- 使用 Python 测试脚本生成和记录测试数据

## 2. 适用场景

- Radxa ROCK 3B 作为主控板，STM32 作为下位机
- 两者之间通过 3.3V TTL UART 连接
- 电脑通过 USB 转串口模块分别连接 Radxa 和 STM32
- 使用 VOFA+ 观察通信内容，辅助查找 TX/RX、波特率、帧格式问题

## 3. 准备工作

### 3.1 硬件

- Radxa ROCK 3B 主板
- STM32 开发板（如 STM32F407）
- 2 个 USB 转 TTL 串口模块（或一个模块用于 Radxa，一个模块用于 STM32）
- 连接线若干
- 电脑一台，安装 VOFA+ 串口调试器

### 3.2 软件

- VOFA+ 串口调试器
- Python 3
- pyserial 库：`pip install pyserial`
- 本工程中的测试脚本：`tools/uart_debug_tool.py`

## 4. 串口接线

### 4.1 推荐接线方式：Radxa 与 STM32 各自接到电脑

1. Radxa UART0（GPIO）接 USB-TTL 模块 A
   - Radxa TX → USB-TTL RX
   - Radxa RX ← USB-TTL TX
   - Radxa GND ↔ USB-TTL GND

2. STM32 USART1 接 USB-TTL 模块 B
   - STM32 TX (PA9) → USB-TTL RX
   - STM32 RX (PA10) ← USB-TTL TX
   - STM32 GND ↔ USB-TTL GND

3. 如果 Radxa 与 STM32 使用同一条总线进行通信，务必确保:
   - Radxa TX 与 STM32 RX 互联
   - Radxa RX 与 STM32 TX 互联
   - 所有 GND 共地
   - 使用 3.3V TTL 电平，禁止直接接 5V TTL

### 4.2 注意事项

- USB-TTL 模块电源线（5V/3.3V）一般不与板子电源并联，除非你确认电源需求。
- 只需共地即可，不推荐将两个模块的 VCC 串联供电。
- 串口线必须是交叉连接：TX→RX、RX→TX。

## 5. VOFA+ 验证步骤

### 5.1 找到串口号

1. 连接 USB-TTL 模块到电脑
2. 在设备管理器中确认两个 COM 端口
3. 记住 Radxa 对应的端口、STM32 对应的端口

### 5.2 VOFA+ 基本设置

- 波特率：`115200`
- 数据位：`8`
- 停止位：`1`
- 校验位：`None`
- 流控：`None`

### 5.3 同时打开两个串口

1. 打开 VOFA+，创建两个串口窗口
2. 一个窗口连接 Radxa 的 COM 端口
3. 另一个窗口连接 STM32 的 COM 端口
4. 确保两个窗口都能正常接收数据

### 5.4 观察通信内容

- 如果 Radxa 发送 UART 数据，STM32 端应能收到可见字节流
- 如果 STM32 有回应，Radxa 端应能看到返回数据
- 可以使用 VOFA+ 的十六进制显示模式，检查帧头、帧尾、校验等

### 5.5 常见验证点

- 看 Radxa 端是否有初始化输出或心跳信息
- 看 STM32 端是否有接收数据
- 通过 VOFA+ 发送简单 ASCII 命令，验证是否收到响应
- 若通信无响应，先断开并检查 TX/RX、GND、波特率

## 6. Python 测试脚本：`tools/uart_debug_tool.py`

本脚本用来辅助调试：
- 同时打开 Radxa 和 STM32 两个串口
- 记录双方实时收发数据
- 在终端输入命令，向指定端口发送数据
- 可用于验证 VOFA+ 与真实串口行为是否一致

### 6.1 使用方法

```bash
python3 tools/uart_debug_tool.py \
  --rock-port COM5 \
  --stm-port COM6 \
  --baud 115200
```

### 6.2 交互模式示例

在脚本运行后，可输入：

- `rock Hello`：向 Radxa 端发送 `Hello`
- `stm status`：向 STM32 端发送 `status`
- `hex rock 0x01 0x02 0x03`：向 Radxa 端发送十六进制字节
- `bridge on`：开启自动转发功能
- `bridge off`：关闭自动转发功能
- `quit`：退出程序

### 6.3 与 VOFA+ 联合验证

1. 在电脑上运行 `tools/uart_debug_tool.py`
2. 使用 VOFA+ 打开同样的两个串口
3. 在 VOFA+ 中观察数据，同时在脚本窗口中查看日志
4. 若 VOFA+ 与脚本均显示相同数据，则串口链路基本正常

## 7. 简单发送工具：`tools/simple_send_tool.py`

如果你只需要控制主板（Radxa）发送数据给 STM32，而不需要监听 STM32 的回应，可以使用这个简化工具。

### 7.1 一次性发送

```bash
# 发送文本消息
python3 tools/simple_send_tool.py --port COM11 --baud 115200 --message "Hello STM32"

# 发送十六进制数据
python3 tools/simple_send_tool.py --port COM11 --baud 115200 --hex "AA 55 01 02"
```

### 7.2 交互模式

```bash
# 进入交互模式，可以反复发送
python3 tools/simple_send_tool.py --port COM11 --baud 115200 --interactive

# 然后在提示符下输入：
> Hello STM32
> hex AA 55 01
> quit
```

### 7.3 适用场景

- 只需单向发送，无需监听回应
- 避免同时打开两个串口可能出现的权限问题
- 快速测试数据发送功能

## 8. 常见问题排查

### 8.1 串口无输出

- 检查 USB-TTL 板是否已正确安装驱动
- 确认端口是否被占用
- 确认连线是否正确：TX→RX、RX→TX、共地
- 验证波特率是否为 115200

### 8.2 出现乱码

- 波特率、数据位、停止位、校验位设置是否一致
- 是否误将串口设为 `7E1`、`8O1` 等
- 是否使用了错误的电平（5V TTL 而非 3.3V TTL）

### 8.3 单向可通信

- 一端的 TX 可能没有正确连接到另一端的 RX
- 一端串口可能未启用发送/接收
- 若 Radxa 发送可见但 STM32 没有响应，可先检查 STM32 固件是否已启动并启用了 UART 接收中断

### 8.4 只要一端可见

- 若只有 Radxa 端能看到数据，而 STM32 端完全无数据，说明接线或 STM32 端配置存在问题
- 若只有 STM32 端能看到数据，而 Radxa 端无响应，说明 Radxa 端输出或接收配置可能异常

---

## 9. 推荐步骤

1. 先单独打开 Radxa 串口，确认 Radxa 正常输出
2. 再单独打开 STM32 串口，确认 STM32 能正常接收并输出
3. 最后同时打开两个串口，确认双方通信
4. 如果需要，可在 VOFA+ 中同时打开十六进制显示，检查帧格式
5. 使用 `tools/uart_debug_tool.py` 进一步记录与发送数据
6. 如果只需要发送数据，使用 `tools/simple_send_tool.py` 更简单
