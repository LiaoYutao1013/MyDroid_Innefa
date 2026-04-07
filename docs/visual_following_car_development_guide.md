# 视觉跟随小车开发文档

## 1. 文档目的

这份文档用于帮助开发和联调以下几部分：

1. ROCK 3B 上位机与 STM32 下位机之间的串口协议。
2. 麦克纳姆轮底盘的速度定义与逆运动学公式。
3. 各器件的连接方式、PWM/串口占用和实际引脚分配。
4. 上位机 ROS2 参数与下位机固件参数之间的对应关系。

如果你现在要检查接线、确认串口方向或重新标定底盘参数，建议优先看这份文档。

---

## 2. 系统总体结构

当前系统按照“上位机决策、下位机执行”的架构工作：

1. ROCK 3B 运行 ROS2 节点。
2. USB 摄像头接到 ROCK 3B，由 YOLO 检测目标。
3. `visual_follower_node.py` 根据目标位置和距离计算：
   - 底盘速度 `vx / vy / omega`
   - Pan 云台角度 `pan_angle`
4. `serial_bridge_node.py` 把这些控制量打包成 UART 协议帧。
5. STM32 通过 `USART1` 接收协议帧，并驱动：
   - TIM3 的 4 路 PWM 控制麦轮电机
   - TIM4_CH1 控制 Pan 云台舵机

---

## 3. 使用的串口与连接方式

### 3.1 串口使用说明

当前实现中，ROS2 上位机默认使用：

- 串口设备：`/dev/ttyS1`
- 波特率：`115200`
- 数据位：`8`
- 校验位：`None`
- 停止位：`1`
- 电平标准：`3.3V TTL`

STM32 侧对应使用：

- 外设：`USART1`
- `PA9` 作为 `USART1_TX`
- `PA10` 作为 `USART1_RX`

### 3.2 串口交叉连接

串口必须交叉连接：

- ROCK 3B `TX` -> STM32 `PA10 / USART1_RX`
- ROCK 3B `RX` -> STM32 `PA9 / USART1_TX`
- ROCK 3B `GND` -> STM32 `GND`

### 3.3 串口接线检查清单

如果串口不通，建议按下面顺序检查：

1. 是否使用了 **3.3V TTL** 串口，而不是 RS232 电平。
2. 是否做了 **TX/RX 交叉连接**。
3. 是否 **共地**。
4. 上位机 YAML 中的 `serial_bridge_node.port` 是否确实是 `/dev/ttyS1`。
5. STM32 工程里是否启用了 `USART1` 中断。
6. ROCK 3B 用户是否有串口设备访问权限。

---

## 4. 新旧串口协议说明

当前系统支持两套协议格式，通过 `flags` 字节里的 `bit3` 区分。

- `bit3 = 0`：旧协议 V1
- `bit3 = 1`：新协议 V2

两套协议都保持 **固定 16 字节长度**，这样下位机解析逻辑简单且稳定。

### 4.1 协议帧格式总览

| 字节偏移 | 长度 | 字段名 | 类型 | 说明 |
|---|---:|---|---|---|
| 0 | 1 | header0 | uint8 | 固定 `0xAA` |
| 1 | 1 | header1 | uint8 | 固定 `0x55` |
| 2 | 1 | sequence | uint8 | 帧序号 |
| 3 | 1 | flags | uint8 | 模式、急停、协议版本 |
| 4~5 | 2 | vx_mmps | int16 | 前进速度，单位 mm/s |
| 6~7 | 2 | vy_mmps | int16 | 左移速度，单位 mm/s |
| 8~9 | 2 | omega_mradps | int16 | 角速度，单位 mrad/s |
| 10~11 | 2 | pan 字段 | int16 | V1/V2 含义不同 |
| 12~13 | 2 | 预留/旧 tilt 字段 | int16 | V1 为 tilt，V2 预留 |
| 14~15 | 2 | crc16 | uint16 | CRC16-CCITT |

### 4.2 flags 字节定义

| 位 | 宏名 | 含义 |
|---|---|---|
| bit0 | `COMMAND_FLAG_AUTO` | 当前命令来自自动模式 |
| bit1 | `COMMAND_FLAG_ESTOP` | 当前命令要求急停 |
| bit2 | `COMMAND_FLAG_VALID` | 当前命令有效 |
| bit3 | `COMMAND_FLAG_PROTOCOL_V2` | 使用 V2 协议 |

### 4.3 新协议 V2 说明

当 `COMMAND_FLAG_PROTOCOL_V2 = 1` 时：

- `bytes 10~11`：`pan_angle_deg`
- 类型：`int16`
- 单位：整数度
- 例如：
  - `90` 表示 90 度
  - `120` 表示 120 度

`bytes 12~13` 在当前版本中保留为 `0`。

### 4.4 旧协议 V1 说明

当 `COMMAND_FLAG_PROTOCOL_V2 = 0` 时：

- `bytes 10~11`：`pan_cdeg`
- 单位：`0.01` 度
- 例如：
  - `9000` 表示 90.00 度
  - `12345` 表示 123.45 度

- `bytes 12~13`：旧版 `tilt_cdeg`

当前 Pan-only 固件仍兼容这种格式，会自动把 `pan_cdeg` 转成整数角度使用。

### 4.5 CRC 校验

CRC 使用：

- 多项式：`0x1021`
- 初始值：`0xFFFF`
- 校验范围：前 `14` 个字节，即 `bytes 0~13`

下位机解析时只有 CRC 正确才会接受这一帧命令。

### 4.6 示例：V2 帧的含义

假设上位机发送：

- `vx = 0.20 m/s`
- `vy = -0.10 m/s`
- `omega = 0.30 rad/s`
- `pan = 120 deg`

则编码后大致为：

- `vx_mmps = 200`
- `vy_mmps = -100`
- `omega_mradps = 300`
- `pan_angle_deg = 120`

---

## 5. 麦克纳姆轮坐标系说明

为了让上位机和下位机的速度定义一致，当前项目采用如下坐标系：

- `x` 正方向：车头朝前
- `y` 正方向：车体左侧
- `z` 正方向：竖直向上
- `omega > 0`：车体绕 z 轴逆时针旋转

速度定义如下：

- `vx > 0`：小车向前走
- `vy > 0`：小车向左横移
- `omega > 0`：小车逆时针旋转

---

## 6. 麦轮逆运动学公式说明

### 6.1 变量定义

- `R`：轮子半径
- `L`：底盘前后半长度
- `W`：底盘左右半宽度
- `k = L + W`

### 6.2 轮速公式

当前固件采用标准麦轮逆运动学：

```text
w_fl = (vx - vy - (L + W) * omega) / R
w_fr = (vx + vy + (L + W) * omega) / R
w_rl = (vx + vy - (L + W) * omega) / R
w_rr = (vx - vy + (L + W) * omega) / R
```

其中：

- `w_fl`：前左轮角速度
- `w_fr`：前右轮角速度
- `w_rl`：后左轮角速度
- `w_rr`：后右轮角速度

### 6.3 公式物理意义

1. `vx` 影响四个轮子同向转动，用于前后运动。
2. `vy` 让左右轮呈不同组合，用于横向平移。
3. `omega` 通过 `(L + W)` 放大为角速度对轮速的贡献，用于原地旋转。

### 6.4 从轮速到 PWM 的处理流程

下位机并不会直接把 `w_fl` 等值输出给电机，而是做如下步骤：

1. 先把每个轮子的角速度除以 `MAX_WHEEL_ANGULAR_SPEED_RADPS`
2. 得到归一化值 `-1.0 ~ 1.0`
3. 如果任何一个轮子的绝对值超过 `1.0`
   - 就把四个轮子统一按比例缩小
4. 再把归一化值映射为 PWM 占空比
5. 符号决定方向脚，绝对值决定 PWM 大小

这样可以保持运动方向不变，同时避免某个轮子先饱和导致运动失真。

---

## 7. 器件连接方式总表

### 7.1 ROCK 3B 与 STM32

| ROCK 3B | STM32F407 | 说明 |
|---|---|---|
| UART TX | `PA10 / USART1_RX` | 串口交叉连接 |
| UART RX | `PA9 / USART1_TX` | 串口交叉连接 |
| GND | GND | 必须共地 |

### 7.2 Pan 云台舵机

| 舵机信号 | STM32 引脚 | 定时器 | 通道 |
|---|---|---|---|
| Pan PWM | `PB6` | `TIM4` | `CH1` |

补充说明：

- 舵机电源建议使用独立 `5V` 稳压供电。
- STM32 只输出 PWM 信号，不建议直接给舵机供电。
- 舵机电源地必须与 STM32 地线共地。

### 7.3 麦轮电机 PWM

| 轮子 | PWM 引脚 | 定时器通道 |
|---|---|---|
| 前左轮 | `PA6` | `TIM3_CH1` |
| 前右轮 | `PA7` | `TIM3_CH2` |
| 后左轮 | `PB0` | `TIM3_CH3` |
| 后右轮 | `PB1` | `TIM3_CH4` |

### 7.4 麦轮电机方向脚

| 轮子 | IN1 | IN2 |
|---|---|---|
| 前左轮 | `PC0` | `PC1` |
| 前右轮 | `PC2` | `PC3` |
| 后左轮 | `PC4` | `PC5` |
| 后右轮 | `PB12` | `PB13` |

### 7.5 电机驱动待机脚

| 功能 | 引脚 |
|---|---|
| Driver STBY | `PB14` |

---

## 8. 实际接线检查建议

建议按下面顺序逐项确认：

### 8.1 电源检查

1. STM32 供电是否稳定。
2. 电机驱动板电源是否独立且电流足够。
3. 舵机是否使用独立 `5V` 电源。
4. 所有地线是否已经共地。

### 8.2 串口检查

1. ROCK TX 是否接到 STM32 RX。
2. ROCK RX 是否接到 STM32 TX。
3. 是否误用了 USB 转串口的 `5V` 电平接口。
4. 上位机是否打开了 `/dev/ttyS1`。

### 8.3 舵机检查

1. Pan 信号线是否真的接到 `PB6` 对应的 `TIM4_CH1`。
2. 云台上电是否会回到约 90 度中位。
3. 如果方向相反，优先改 `PAN_SERVO_REVERSED`。

### 8.4 麦轮检查

1. 4 路 PWM 是否分别接到 `TIM3` 四个通道。
2. 4 个方向脚是否和定义一致。
3. 如果某个轮子方向相反，优先改 `FRONT_LEFT_MOTOR_REVERSED` 等宏，而不是立刻改公式。

---

## 9. 上位机与下位机参数对应关系

| 上位机参数 | 下位机相关宏/逻辑 | 说明 |
|---|---|---|
| `serial_bridge_node.port` | `USART1` | 实际通信串口 |
| `serial_bridge_node.baudrate` | `MX_USART1_UART_Init()` | 波特率必须一致 |
| `gimbal.pan_neutral` | `PAN_SERVO_NEUTRAL_DEG` | 建议保持一致 |
| `gimbal.pan_max_angle` | `PAN_SERVO_MAX_DEG` / 上位机限幅 | 建议匹配 |
| `max_linear_x_mps` | `MAX_BODY_VX_MPS` | 上下位机都会限幅 |
| `max_linear_y_mps` | `MAX_BODY_VY_MPS` | 上下位机都会限幅 |
| `max_angular_z_radps` | `MAX_BODY_OMEGA_RADPS` | 上下位机都会限幅 |

---

## 10. 推荐联调顺序

### 第一步：只测上位机

1. 运行 `camera_test_launch.py`
2. 检查 YOLO 是否能输出目标框
3. 检查 `visual_follower_node` 是否输出 Pan 和底盘速度
4. 检查 `mock_serial_bridge` 是否打印期望结果

### 第二步：只测 Pan 云台

1. STM32 下载固件
2. 只接 Pan 舵机，不接底盘电机
3. 运行 `gimbal_test_launch.py`
4. 手动发布 `/vision/target_bbox`
5. 观察云台是否随着目标 x 坐标变化而左右转动

### 第三步：测串口通信

1. 连接 ROCK 3B 与 STM32 串口
2. 保持底盘离地
3. 运行 `bringup.launch.py`
4. 观察 Pan 云台是否跟随变化
5. 再检查底盘 4 个轮子的旋转方向是否与预期一致

---

## 11. 关键源码位置索引

- 串口协议头文件：
  - `firmware/stm32_visual_follower/Core/Inc/protocol.h`
- 串口协议解析：
  - `firmware/stm32_visual_follower/Core/Src/protocol.c`
- 麦轮公式与 Pan 控制：
  - `firmware/stm32_visual_follower/Core/Src/motor_control.c`
- 串口打包：
  - `ros2_ws/src/visual_following_car/visual_following_car/serial_bridge_node.py`
- 视觉跟随控制：
  - `ros2_ws/src/visual_following_car/visual_following_car/visual_follower_node.py`

---

## 12. 结论

当前这套实现的关键连接关系可以一句话总结为：

- **ROCK 3B 通过 `/dev/ttyS1` 以 `115200 8N1` 和 STM32 的 `USART1` 通讯**
- **底盘 4 路 PWM 使用 `TIM3_CH1~CH4`**
- **Pan 云台使用 `TIM4_CH1 / PB6`**
- **所有设备必须共地，串口必须交叉连接，舵机建议独立 5V 供电**

如果你检查接线时发现任何一条和这里不一致，建议优先按这份文档统一。