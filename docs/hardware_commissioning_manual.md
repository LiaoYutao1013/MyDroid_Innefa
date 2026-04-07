# 视觉跟随小车硬件联调手册

## 1. 文档定位

这份手册面向“准备把系统从代码带到真实硬件”的阶段，重点回答下面几个问题：

1. 现在各个器件到底应该怎么接。
2. 串口协议具体长什么样，怎么抓包检查。
3. 麦轮公式到底对应哪种坐标系，出现“前进变横移”时该查哪里。
4. 不同功能应该怎样拆开单测，避免一上来就全链路联调。
5. `.rknn` 模型应该放在工程什么位置，后面怎么引用最稳妥。

这份手册尽量和已经存在的源码、YAML 参数、STM32 引脚定义保持一致，方便边看边对照代码。

---

## 2. 当前系统分层

当前工程可以按 4 层来理解：

### 2.1 视觉感知层

- 设备：USB 摄像头或 CSI 摄像头
- 运行位置：ROCK 3B / Windows 调试机
- 主要程序：
  - `yolo_detection_node.py`
  - 独立 Windows 视觉测试脚本 `tools/windows_vision_only_test.py`

这一层只负责“看见目标并输出目标框”，不直接操作底盘。

### 2.2 跟随决策层

- 运行位置：ROCK 3B
- 主要程序：`visual_follower_node.py`
- 输入：
  - 目标框中心位置
  - 目标估计距离
  - 手柄模式切换/急停状态
- 输出：
  - 底盘速度 `vx / vy / omega`
  - Pan 云台目标角 `pan_angle`

这一层是“脑子”，决定怎么追人、怎么转头。

### 手柄映射与雷神（Thunderobot）兼容性

不同品牌游戏手柄的轴/按键索引可能不一致。为方便适配雷神等品牌，系统在 `joy_teleop_node` 中增加了“映射助手”。使用方式：

1. 启动手动遥控节点：

   ```bash
   ros2 launch visual_following_car teleop_manual.launch.py
   ```

2. 启用映射助手：

   ```bash
   ros2 param set /joy_teleop_node controller_model mapping_assistant
   ```

3. 按日志提示操作：当节点提示“Move the next control”时移动对应摇杆；当提示“Press the next button”时按下对应按键。完成后节点会输出一段 YAML，直接粘回 `config/visual_following_car.yaml` 的 `joy_teleop_node.ros__parameters` 下即可。

4. 调试替代方法：

   - 查看原始消息：`ros2 topic echo /joy`。
   - Linux 下用 `jstest /dev/input/js0` 查看索引与当前值。

映射助手对新手非常友好：无需事先知道索引，按提示操作即可得到可复制的 YAML 配置片段。

### 2.3 通信桥接层

- 运行位置：ROCK 3B
- 主要程序：`serial_bridge_node.py`
- 作用：
  - 把 ROS2 里的速度/角度命令转换成 UART 固定帧
  - 发给 STM32

这一层是“翻译官”，负责把 ROS2 消息翻译成下位机能懂的字节流。

### 2.4 执行控制层

- 运行位置：STM32F407
- 主要程序：
  - `protocol.c`
  - `motor_control.c`
  - `main.c`
- 作用：
  - 解析串口帧
  - 驱动 4 路麦轮 PWM
  - 驱动 Pan 云台舵机 PWM
  - 做超时停车和云台回中保护

这一层是“肌肉”，只负责按命令执行，不做高层目标判断。

---

## 3. 设备连接总览

## 3.1 上位机与下位机的串口连接

当前设计使用：

- ROCK 3B 串口设备：`/dev/ttyS1`
- 波特率：`115200`
- 帧格式：`8N1`
- 电平标准：`3.3V TTL`
- STM32 外设：`USART1`

### 3.1.1 交叉接法

必须使用 UART 标准交叉接法：

| ROCK 3B | STM32F407 | 说明 |
|---|---|---|
| UART TX | `PA10 / USART1_RX` | 上位机发，下位机收 |
| UART RX | `PA9 / USART1_TX` | 下位机发，上位机收 |
| GND | GND | 必须共地 |

### 3.1.2 串口接线最常见错误

如果串口完全没有响应，优先查这 5 项：

1. 是否把 `TX` 和 `RX` 直接同名相连了。
2. 是否漏接 `GND`。
3. 是否误用了 `5V UART` 转换板。
4. ROCK 3B 是否真的打开了 `/dev/ttyS1`。
5. STM32 是否启用了 `USART1` 中断接收。

---

## 3.2 Pan 云台连接

当前固件中 Pan 舵机默认接法如下：

| 功能 | STM32 引脚 | 定时器 | 通道 |
|---|---|---|---|
| Pan 舵机 PWM | `PB6` | `TIM4` | `CH1` |

### 3.2.1 Pan 云台供电建议

- 舵机信号线：接 `PB6`
- 舵机电源：建议外部独立 `5V`
- 舵机地线：必须和 STM32 地线共地

不建议让 STM32 板载 `5V` 或 USB 口直接硬拖大舵机，尤其在云台启动、抖动或卡住时容易掉压。

---

## 3.3 麦轮底盘连接

### 3.3.1 PWM 输出

| 车轮 | STM32 引脚 | 定时器通道 |
|---|---|---|
| 前左轮 | `PA6` | `TIM3_CH1` |
| 前右轮 | `PA7` | `TIM3_CH2` |
| 后左轮 | `PB0` | `TIM3_CH3` |
| 后右轮 | `PB1` | `TIM3_CH4` |

### 3.3.2 电机方向脚

| 车轮 | IN1 | IN2 |
|---|---|---|
| 前左轮 | `PC0` | `PC1` |
| 前右轮 | `PC2` | `PC3` |
| 后左轮 | `PC4` | `PC5` |
| 后右轮 | `PB12` | `PB13` |

### 3.3.3 驱动器待机脚

| 功能 | STM32 引脚 |
|---|---|
| Driver STBY | `PB14` |

---

## 3.4 摄像头连接

### USB 摄像头

- 直接接到 ROCK 3B USB 口
- Linux 下通常枚举为 `/dev/video0`

检查命令：

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

### Windows 下 USB 摄像头

- 通常通过 OpenCV 的摄像头索引打开
- 默认摄像头号一般是 `0`

如果 Windows 上打开失败，依次尝试：

1. `--camera 0`
2. `--camera 1`
3. 关闭占用摄像头的软件，比如微信、QQ、浏览器、OBS

---

## 4. 串口协议说明

当前协议为固定 16 字节帧，兼容旧协议 V1 和新协议 V2。

## 4.1 固定帧结构

| 字节偏移 | 长度 | 字段名 | 类型 | 含义 |
|---|---:|---|---|---|
| 0 | 1 | `header0` | `uint8` | 固定 `0xAA` |
| 1 | 1 | `header1` | `uint8` | 固定 `0x55` |
| 2 | 1 | `sequence` | `uint8` | 帧序号 |
| 3 | 1 | `flags` | `uint8` | 模式/急停/协议版本 |
| 4-5 | 2 | `vx_mmps` | `int16` | 前进速度，单位 `mm/s` |
| 6-7 | 2 | `vy_mmps` | `int16` | 左移速度，单位 `mm/s` |
| 8-9 | 2 | `omega_mradps` | `int16` | 角速度，单位 `mrad/s` |
| 10-11 | 2 | `pan` | `int16` | V1/V2 含义不同 |
| 12-13 | 2 | 预留 | `int16` | V1 为旧 `tilt` 字段，V2 预留 |
| 14-15 | 2 | `crc16` | `uint16` | 对前 14 字节做 CRC16-CCITT |

## 4.2 flags 位定义

| 位 | 宏名 | 含义 |
|---|---|---|
| bit0 | `COMMAND_FLAG_AUTO` | 自动模式输出 |
| bit1 | `COMMAND_FLAG_ESTOP` | 急停状态 |
| bit2 | `COMMAND_FLAG_VALID` | 当前命令有效 |
| bit3 | `COMMAND_FLAG_PROTOCOL_V2` | 新协议 V2 |

## 4.3 V1 与 V2 的关键区别

### V1 旧协议

- `bytes 10-11`：`pan_cdeg`
- 单位：`0.01 度`
- 示例：
  - `9000` 表示 `90.00 度`
  - `12000` 表示 `120.00 度`

### V2 新协议

- `bytes 10-11`：`pan_angle_deg`
- 单位：整数度
- 示例：
  - `90` 表示 `90 度`
  - `120` 表示 `120 度`

### 为什么保留双协议

这样做是为了避免你后面出现“上位机已更新、下位机还是老固件”的联调断层。  
即使一边先升级，另一边没来得及刷，也不至于直接完全失联。

## 4.4 CRC 规则

- 多项式：`0x1021`
- 初值：`0xFFFF`
- 校验范围：`bytes 0~13`

下位机只有在 CRC 正确时才接收本帧。

---

## 5. 麦轮坐标系与公式说明

## 5.1 坐标系定义

当前工程统一采用以下车体坐标系：

- `x` 正方向：车头朝前
- `y` 正方向：车体左侧
- `z` 正方向：竖直向上
- `omega > 0`：绕 `z` 轴逆时针旋转

所以：

- `vx > 0`：小车前进
- `vy > 0`：小车向左平移
- `omega > 0`：小车逆时针原地旋转

这是最关键的基础定义。  
如果你后面发现“视觉输出是对的，但实车方向全反”，十有八九不是视觉问题，而是这里的坐标约定和接线/翻转宏不一致。

## 5.2 逆运动学公式

下位机中使用的麦轮逆运动学公式为：

```text
w_fl = (vx - vy - (L + W) * omega) / R
w_fr = (vx + vy + (L + W) * omega) / R
w_rl = (vx + vy - (L + W) * omega) / R
w_rr = (vx - vy + (L + W) * omega) / R
```

其中：

- `R`：轮子半径
- `L`：底盘前后半长度
- `W`：底盘左右半宽度
- `w_fl`：前左轮角速度
- `w_fr`：前右轮角速度
- `w_rl`：后左轮角速度
- `w_rr`：后右轮角速度

## 5.3 这些公式怎么理解

### 只给 `vx`

如果只前进，不横移、不旋转：

```text
vx > 0, vy = 0, omega = 0
```

那么四个轮子应同向转动，小车直线前进。

### 只给 `vy`

如果只做横向平移：

```text
vx = 0, vy > 0, omega = 0
```

左右轮组合会呈现典型麦轮横移模式。  
如果实车不是横移，而是斜着跑，优先检查：

1. 车轮安装方向是否一致。
2. 电机方向线是否接反。
3. `FRONT_LEFT_MOTOR_REVERSED` 等宏是否配置错。

### 只给 `omega`

如果只原地旋转：

```text
vx = 0, vy = 0, omega > 0
```

四轮会形成相互对抗的转动组合，使车体逆时针旋转。

## 5.4 从公式到 PWM 的过程

固件不会直接把轮速公式结果原样送给电机，而是做了 3 步保护：

1. 先算出四个轮子的归一化速度。
2. 如果某个轮子超出 `[-1, 1]`，则四轮一起按比例缩放。
3. 再把归一化结果映射为 PWM 占空比和方向脚状态。

这样做的目的是：

- 保留运动方向比例关系
- 避免某一个轮子先饱和把整车运动“拉歪”

---

## 6. `.rknn` 模型应该放在哪里

我建议统一放在：

```text
ros2_ws/src/visual_following_car/models/
```

推荐结构：

```text
ros2_ws/src/visual_following_car/models/
├── README.md
├── yolov8n.pt
├── yolov8n_rk3568.rknn
└── person_follow_yolov8n_rk3568.rknn
```

这样做有 4 个好处：

1. 模型和 ROS 包放在同一个工程里，迁移机器时不容易漏文件。
2. `.pt`、`.onnx`、`.rknn` 可以并排存放，方便对照。
3. 后面做 YAML 参数切换时，路径比较统一。
4. 以后如果你想把模型也纳入版本管理或发版包，结构清晰。

## 6.1 开发阶段最稳妥的引用方式

如果你还在频繁换模型，最稳妥的是直接在 YAML 里写**绝对路径**，例如：

```yaml
model_path: /home/rock/MyDroid/ros2_ws/src/visual_following_car/models/yolov8n_rk3568.rknn
```

原因很简单：

- 当前节点参数 `model_path` 本质上就是一个字符串
- 绝对路径最不容易受启动目录影响
- 便于快速排查“模型文件到底有没有被找到”

## 6.2 如果以后想走安装路径

如果你希望模型跟着包一起安装到 `install/`，那就：

1. 把模型放进 `models/`
2. 重新 `colcon build`
3. 再用安装后的 share 目录路径引用

但在联调初期，我仍然建议先用源码目录里的绝对路径，排障更直接。

## 6.3 Windows 纯视觉测试时要不要用 `.rknn`

通常**不建议**。

原因：

- `.rknn` 主要是给 Rockchip RKNN Runtime / RKNN Toolkit 运行链路准备的
- Windows 上做纯视觉验证时，最方便的是用：
  - `.pt`
  - 或 `onnx`

Windows 纯视觉测试的目标是验证：

1. 摄像头是否能打开
2. 模型能否检测到目标
3. 目标中心点和模拟 Pan 控制是否符合预期

这个阶段优先追求“能快、能看、能改”，而不是先卡在部署格式上。

---

## 7. 独立测试各个功能的建议顺序

下面这套顺序是为了尽量降低联调耦合度。  
简单说就是：**一次只验证一层，不把所有问题堆到一起。**

## 7.1 第 0 步：只检查供电与接线

上电前先确认：

1. STM32 板供电稳定。
2. 电机驱动器供电独立且电流足够。
3. 舵机供电独立 5V。
4. ROCK 3B、STM32、舵机电源、驱动器地线共地。
5. 串口 TX/RX 交叉连接。

这一阶段不要插满所有器件后直接上电跑程序。

## 7.2 第 1 步：仅测试 Windows 视觉链路

目标：完全不依赖 ROS2、不依赖 STM32，只验证“摄像头 + 模型 + 跟随角度计算”。

入口脚本：

- [tools/windows_vision_only_test.py](e:\Mech Engineering\MyDroid\tools\windows_vision_only_test.py)
- [tools/run_windows_vision_only_test.ps1](e:\Mech Engineering\MyDroid\tools\run_windows_vision_only_test.ps1)

安装依赖：

```powershell
cd "E:\Mech Engineering\MyDroid"
py -m pip install -r .\tools\windows_vision_only_requirements.txt
```

运行：

```powershell
cd "E:\Mech Engineering\MyDroid"
.\tools\run_windows_vision_only_test.ps1
```

如果摄像头号不是 0：

```powershell
.\tools\run_windows_vision_only_test.ps1 --camera 1
```

观察点：

1. 画面是否正常显示。
2. 检测框是否稳定。
3. 终端是否输出 `FPS / center_x / pan_angle`。
4. 人在画面左边时，模拟 Pan 角是否朝左侧修正。

## 7.3 第 2 步：仅测试 ROCK 3B 视觉 ROS 链路

目标：验证 ROS2 环境里，摄像头、YOLO、跟随节点之间的消息链路。

启动：

```bash
cd ~/MyDroid/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch visual_following_car camera_test_launch.py
```

观察点：

1. `usb_cam` 是否正常发布 `/image_raw`
2. `yolo_detection_node` 是否发布 `/vision/target_bbox`
3. `visual_follower_node` 是否打印
   - 目标坐标
   - 跟随速度
   - Pan 角

这一阶段仍然不接 STM32。

## 7.4 第 3 步：仅测试串口链路

目标：确认 ROCK 3B 到 STM32 的 UART 是通的。

建议做法：

1. STM32 先只刷协议解析和最小回中逻辑。
2. 暂时不要接电机。
3. 只接串口和 Pan 舵机。

如果想更底层检查，可以：

- 用 USB 转串口模块抓 STM32 TX
- 或在 STM32 端临时增加 LED/串口回显，用于确认收到帧

重点观察：

1. 下位机是否持续收到固定帧
2. CRC 错误率是否为 0
3. 丢命令时是否 500ms 内触发保护

## 7.5 第 4 步：仅测试 Pan 云台

目标：验证 Pan 舵机角度映射和方向是否正确。

启动：

```bash
cd ~/MyDroid/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch visual_following_car gimbal_test_launch.py
```

然后手动发布一个模拟目标：

```bash
ros2 topic pub /vision/target_bbox std_msgs/msg/Float32MultiArray "{data: [0.25, 0.5, 0.2, 0.4, 0.9, 0.08, 1.5, 640.0, 480.0]}"
```

观察点：

1. Pan 是否朝预期方向偏转
2. 禁用云台时是否回到中位
3. 超时后是否回中

如果方向反了，优先查：

1. `PAN_SERVO_REVERSED`
2. 上位机 `gimbal.pan_kp` 符号理解
3. 舵机机械安装朝向

## 7.6 第 5 步：仅测试底盘手动控制

目标：验证麦轮方向和底盘基础响应。

启动：

```bash
cd ~/MyDroid/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch visual_following_car teleop_manual.launch.py
```

测试顺序建议：

1. 只测前进/后退
2. 再测左移/右移
3. 最后测原地旋转

每测一种运动，只给单一输入，不要混合操作。

如果前进不对：

- 查电机方向脚
- 查四轮安装朝向
- 查 `*_MOTOR_REVERSED`

如果横移不对：

- 优先怀疑轮子滚子方向装反
- 其次检查某一侧电机方向翻转宏错误

## 7.7 第 6 步：测试自动跟随但先不让底盘跑

目标：先看视觉是否会正确驱动 Pan，再决定是否放开底盘。

做法：

1. 接摄像头
2. 接 Pan 舵机
3. 暂时断开电机供电
4. 运行完整视觉链路

这样即使跟随参数还没调好，小车也不会突然窜出去。

## 7.8 第 7 步：全链路联调

条件满足后再做：

1. 视觉检测正常
2. Pan 云台正常
3. 串口正常
4. 底盘手动控制正常
5. 急停按钮确认可用

然后再上自动跟随。

---

## 8. 常见故障与快速定位

## 8.1 看不到目标框

优先检查：

1. 摄像头是否打开
2. 模型路径是否正确
3. 模型类别是否包含 `person`
4. `confidence_threshold` 是否过高

## 8.2 Pan 云台一直抖

优先检查：

1. 舵机供电是否掉压
2. 机械结构是否卡滞
3. `gimbal.pan_kp` 是否过大
4. 目标框中心是否抖动过大

## 8.3 小车向前时斜着跑

优先检查：

1. 某个轮子方向反了
2. 轮子安装方向不一致
3. `*_MOTOR_REVERSED` 宏配置错误

## 8.4 串口偶发失控

优先检查：

1. 地线是否稳定共地
2. 波特率是否一致
3. 线是否过长、干扰过大
4. CRC 是否频繁错误

---

## 9. 推荐的联调记录方式

每次联调建议记录下面几项：

1. 当前固件版本
2. 当前 ROS2 参数文件
3. 当前模型文件名
4. 当前接线改动
5. 当前现象
6. 你做了什么修改
7. 修改后现象是否改善

这会让后续排障速度快很多，尤其是多次改参数之后。

---

## 10. 结论与落地建议

如果你现在准备继续往前推，我建议按下面这个顺序最省时间：

1. 先在 Windows 跑独立视觉脚本，确认摄像头和检测没问题。
2. 再在 ROCK 3B 跑 `camera_test_launch.py`，确认 ROS2 链路没问题。
3. 然后只接 Pan 舵机，跑 `gimbal_test_launch.py`。
4. 最后才接电机和底盘。

`.rknn` 模型的推荐放置位置就是：

```text
ros2_ws/src/visual_following_car/models/
```

联调初期建议直接在 YAML 中写它的绝对路径。
