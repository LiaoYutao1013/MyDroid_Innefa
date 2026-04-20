# PS2手柄直连STM32旁路控制指南

## 1. 适用场景

当你希望在以下场景中绕过 Radxa ROCK 3B，直接由 STM32 控制麦轮底盘时，可以启用本方案：

1. 视觉链路尚未联通，但你要先验证底盘运动学和电机方向。
2. Radxa 端系统还没启动，想先做纯底盘联调。
3. 现场排障时，需要一个不依赖 ROS2 / UART 上位机的“本地安全控制通道”。

当前实现的行为是：

- 默认仍然是 `UART(Radxa ROCK 3B) -> STM32 -> 底盘`。
- 当 PS2 手柄按下 `START` 后，进入 STM32 本地旁路模式。
- 旁路模式下，STM32 优先执行 PS2 手柄命令，不再服从 Radxa 发来的 UART 速度命令。
- 若手柄断链、接收器失联或触发本地急停，STM32 会直接停车，不会自动切回 UART。

---

## 2. 默认接线方式

当前固件默认把 PS2 接收器接到 STM32F407 的 `PC0 ~ PC3`，使用软件时序方式模拟 PS2 串行协议。

### 2.1 接线表

| PS2接收器引脚 | 作用 | STM32默认引脚 | 说明 |
|---|---|---|---|
| `ATT / CS` | 帧选通信号 | `PC0` | 代码宏：`PS2_ATT_Pin` |
| `CMD` | STM32 发命令 | `PC1` | 代码宏：`PS2_CMD_Pin` |
| `CLK` | STM32 时钟输出 | `PC2` | 代码宏：`PS2_CLK_Pin` |
| `DAT` | 接收器回传数据 | `PC3` | 代码宏：`PS2_DAT_Pin` |
| `VCC` | 电源 | `3.3V` | 优先使用 3.3V 供电 |
| `GND` | 地 | `GND` | 必须共地 |
| `ACK` | 应答 | 不接 | 当前代码未使用 |
| `MOTOR / VIB` | 震动电机 | 不接 | 当前代码未使用 |

### 2.2 接线示意

```text
PS2无线接收器                STM32F407VET6
------------------------------------------------
ATT / CS   ----------------> PC0
CMD        ----------------> PC1
CLK        ----------------> PC2
DAT        <---------------- PC3
VCC        ----------------> 3.3V
GND        ----------------> GND
ACK        ---- 不接 ----
MOTOR      ---- 不接 ----
```

### 2.3 电平注意事项

1. 优先选用可以在 `3.3V` 下正常工作的 PS2 无线接收器。
2. 如果你的接收器必须使用 `5V` 供电，请确认 `DAT/ACK` 不会直接输出 5V 到 STM32。
3. 如果无法确认，必须增加电平转换或分压，避免损坏 STM32 GPIO。

### 2.4 如果你已经焊到了别的 GPIO

只需要修改 [main.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/main.h) 中这 4 组宏：

- `PS2_ATT_*`
- `PS2_CMD_*`
- `PS2_CLK_*`
- `PS2_DAT_*`

---

## 3. 固件代码位置

本次已经把 PS2 旁路控制代码接入到当前 STM32 固件主链路：

- 驱动头文件：[ps2_gamepad.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/ps2_gamepad.h)
- 驱动实现：[ps2_gamepad.c](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Src/ps2_gamepad.c)
- 主控接入：[main.c](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Src/main.c)
- 引脚映射：[main.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/main.h)
- 参数配置：[app_config.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/app_config.h)

控制逻辑概括如下：

1. `PS2_Gamepad_Init()` 初始化 GPIO 与微秒延时，并尝试把手柄切到模拟模式。
2. 主循环按 `20 ms` 周期轮询手柄。
3. `START` 按键切换“PS2 本地旁路模式”。
4. `SELECT` 按键触发“本地急停并退出旁路模式”。
5. 旁路模式激活时，STM32 直接把摇杆映射为 `vx / vy / omega`，调用 `MotorControl_SetBodyVelocity()` 控制麦轮。

---

## 4. 手柄输入映射

当前固件默认的 PS2 输入映射如下：

| 手柄输入 | 默认功能 | 说明 |
|---|---|---|
| `START` | 切换 PS2 旁路模式 | 再按一次退出旁路模式 |
| `SELECT` | 本地急停 | 停车并退出旁路模式 |
| 左摇杆 `Y` | 前进 / 后退 | 向上推为前进 |
| 左摇杆 `X` | 左右平移 | 向右推为车体向右平移 |
| 右摇杆 `X` | 原地旋转 | 向右推为顺时针旋转 |
| `L1` | 慢速档 | 约 `35%` 速度，适合桌面联调 |
| `R1` | 快速档 | `100%` 速度，适合地面跑车 |
| 其他按键 | 预留 | 当前底盘模式未使用 |

### 4.1 默认速度缩放

定义在 [app_config.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/app_config.h)：

- `PS2_GAMEPAD_NORMAL_SCALE = 0.60f`
- `PS2_GAMEPAD_SLOW_SCALE = 0.35f`
- `PS2_GAMEPAD_FAST_SCALE = 1.00f`

如果你觉得默认速度过快或过慢，只需要改这三个宏。

### 4.2 摇杆坐标系约定

底盘控制最终映射到车体速度：

- `vx > 0`：车头向前
- `vy > 0`：车体向左
- `omega > 0`：车体逆时针旋转

因此代码中做了这些符号转换：

- 左摇杆向上 -> `vx` 为正
- 左摇杆向右 -> `vy` 为负（车体向右）
- 右摇杆向右 -> `omega` 为负（顺时针）

---

## 5. 手柄调试方法

### 5.1 先做最小系统验证

建议按下面顺序调试：

1. 先只接 `PS2接收器 + STM32 + 电源`，不接 Radxa。
2. 确认接收器能上电，手柄和接收器能配对。
3. 再接入电机驱动和 4 个麦轮。
4. 最后验证 `START`、`SELECT` 和三个摇杆通道。

### 5.2 推荐的调试观察量

如果你用 ST-LINK / Keil / CubeIDE 在线调试，建议把下面变量加入 Watch 窗口：

- `g_ps2_state.connected`
- `g_ps2_state.analog_mode`
- `g_ps2_state.lx`
- `g_ps2_state.ly`
- `g_ps2_state.rx`
- `g_ps2_manual_enabled`
- `g_ps2_estop_latched`

**预期现象：**

1. 接收器未连接或未配对时，`g_ps2_state.connected = false`。
2. 手柄进入模拟模式后，`g_ps2_state.analog_mode = true`。
3. 摇动左摇杆 / 右摇杆时，`lx / ly / rx` 应在 `0 ~ 255` 间变化，中位接近 `128`。
4. 按一下 `START` 后，`g_ps2_manual_enabled` 应在 `0 / 1` 间切换。
5. 按一下 `SELECT` 后，`g_ps2_estop_latched = 1`，底盘应立刻停车。

### 5.3 没有在线调试器时怎么排查

可以按下面方式做硬件层排查：

1. 用万用表先确认接收器 `VCC/GND` 正常。
2. 用示波器或逻辑分析仪看 `PC2(PS2_CLK)` 是否每 `20 ms` 左右输出一组脉冲。
3. 看 `PC0(PS2_ATT)` 是否会在一帧开始时拉低。
4. 看 `PC3(PS2_DAT)` 是否跟随时钟产生数据变化。

**如果 `CLK` 有脉冲但 `DAT` 一直保持高电平：**

- 接收器未供电
- 接收器未配对
- `DAT` 接线错误
- 接收器电平不兼容

### 5.4 手柄配对建议

不同品牌的 2.4G PS2 手柄配对方式略有差异，但通常都是下面两类：

1. 接收器上电后自动与手柄配对。
2. 先按接收器上的 `PAIR / CONNECT` 小按钮，再按手柄的 `MODE / ANALOG / START` 组合键。

建议你在第一次使用时确认两件事：

- 手柄已经切到模拟模式，而不是数字方向键模式。
- 手柄中位时摇杆读数接近 `128`，而不是固定卡在 `0/255`。

---

## 6. 现场使用建议

### 6.1 推荐操作顺序

1. 底盘上电，确认四轮悬空。
2. 接收器上电并与手柄配对。
3. 先不要按 `START`，确认此时底盘不应动作。
4. 轻推摇杆，同时按 `START` 进入旁路模式。
5. 先测小幅前后、再测平移、再测旋转。
6. 方向不对时，优先调整：
   - [app_config.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/app_config.h) 中的 `*_MOTOR_REVERSED`
   - [main.h](/E:/Mech%20Engineering/MyDroid_Innefa/firmware/stm32_visual_follower/Core/Inc/main.h) 中的 PS2 引脚映射

### 6.2 安全建议

1. 第一次上电调试时务必让车轮离地。
2. `SELECT` 本地急停先验证成功，再做地面测试。
3. 旁路模式下如果手柄断链，当前代码会保持本地停车，不会切回 UART。
4. 真正上地跑车前，先用 `L1` 慢速档确认坐标系完全正确。

---

## 7. 与当前工程其它控制链路的关系

当前工程同时支持两条控制链路：

### 7.1 正常模式

`Radxa ROCK 3B -> UART -> STM32 -> 麦轮底盘`

用于：

- 视觉跟随
- ROS2 手柄遥控
- 上位机控制与调试

### 7.2 旁路模式

`PS2手柄 -> PS2无线接收器 -> STM32 -> 麦轮底盘`

用于：

- 绕过 Radxa 直接控车
- 纯底盘联调
- 现场快速排障

当前旁路模式只控制麦轮底盘，不初始化 Pan 舵机、云台或视觉链路。
