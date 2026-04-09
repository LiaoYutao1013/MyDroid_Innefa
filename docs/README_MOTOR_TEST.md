# 电机独立测试快速入门指南

## 📋 文件清单

本测试方案包含以下新增文件：

### 文档
- **`docs/底盘电机驱动独立测试方案.md`** ← 完整测试方案（从这里开始！）
- **`docs/硬件接线与故障排查详细指南.md`** ← 硬件接线与排查
- **`README_MOTOR_TEST.md`** ← 本文件

### 固件代码
- **`firmware/stm32_visual_follower/Core/Inc/motor_test.h`** ← 电机测试API
- **`firmware/stm32_visual_follower/Core/Src/motor_test.c`** ← 电机测试实现
- **`firmware/stm32_visual_follower/Core/Inc/motor_test_config.h`** ← 电机配置头文件
- **`firmware/stm32_visual_follower/Core/Src/main_motor_test_example.c`** ← main.c集成示例

### 上位机工具
- **`tools/motor_test_tool.py`** ← Radxa ROCK 3B 上位机测试工具

---

## 🚀 30秒快速开始

### 硬件连接（5分钟）
1. 连接4个520电机到L298N驱动模块
2. L298N的IN1-IN4接到STM32的GPIO
3. L298N的OUT接电机
4. 编码器A/B线接到STM32的TIM输入捕获引脚
5. UART连接(STM32的TX/RX到Radxa ROCK 3B)
6. **所有GND必须共接！**

参考：`docs/硬件接线与故障排查详细指南.md` 第1-2章

### STM32固件编译（10分钟）
```bash
# 1. 在STM32CubeIDE中打开你的项目
# 2. 复制以下文件到项目：
#    - motor_test.h → Core/Inc/
#    - motor_test.c → Core/Src/
#    - motor_test_config.h → Core/Inc/

# 3. 修改 Core/Src/main.c，在定时器初始化后添加：
TIM_HandleTypeDef *encoder_tims[4] = {&htim2, &htim3, &htim4, &htim5};
MotorTest_Init(&htim2, encoder_tims);

# 4. 编译
Build > Build Project

# 5. 烧录到STM32
Debug > Debug As > Embedded C/C++ Application
```

### Radxa ROCK 3B 上位机（5分钟）
```bash
# 1. 连接UART转USB模块到Radxa的GPIO UART或USB
# 2. 在Radxa上运行测试工具
cd ~/MyDroid_Innefa
python3 tools/motor_test_tool.py --port /dev/ttyUSB0 --baud 115200

# 3. 在交互界面输入命令：
> M 0 300      # 启动电机0，30%功率
> E 0          # 读取电机0编码器
> S            # 停止所有电机
> Q            # 退出
```

---

## 🎯 典型测试流程

### 第一阶段：硬件验证（通电测试）

```bash
# 步骤1：断电状态检查
□ 用万用表检查12V电源正负极
□ 确认电机与驱动模块接线无误
□ 确认编码器A/B线接入正确GPIO
□ 确认GND共接无断开

# 步骤2：上电（无电机运转）
□ L298N上的LED是否亮？
□ STM32上的LED是否闪烁？
□ 有无异味、烧焦味？

# 步骤3：UART通信
□ 打开串口监视器（115200波特率）
□ 应该看到："Motor Test Firmware Started"
□ 输入"H"应该收到帮助信息
```

### 第二阶段：单电机测试

```bash
# 步骤1：启动前左电机（电机0）
> M 0 100
期望：电机缓慢转起，无异响，无烧焦味

# 步骤2：逐步增加功率
> M 0 200
> M 0 300
> M 0 500
期望：转速线性增加

# 步骤3：读取编码器
> E 0
期望：输出类似 "count=1500 rpm=120"

# 步骤4：反向测试
> M 0 -300
期望：电机反向转，编码器计数减少

# 步骤5：重复测试其他电机
> M 1 300  # 电机1 (前右)
> M 2 300  # 电机2 (后左)
> M 3 300  # 电机3 (后右)
```

### 第三阶段：四电机同步测试

```bash
# 使用Python工具的自动测试
> T           # 自动同步测试（5秒）

期望输出：
  1.0s: M0=125rpm M1=128rpm M2=126rpm M3=127rpm
  2.0s: M0=125rpm M1=128rpm M2=126rpm M3=127rpm
  ...
  同步性: 98.5% ✓

如果有偏差 > 5%：
  □ 检查电机是否损坏
  □ 运行速度补偿校准（见下面）
```

---

## 📊 数据解读与诊断

### 编码器数据异常

| 症状 | 原因 | 解决方案 |
|------|------|--------|
| 计数不增加 | 编码器未接或故障 | 检查接线，用万用表测编码器输出 |
| 计数快速跳跃 | 信号干扰 | 加屏蔽线，编码器信号线远离PWM线 |
| 计数反向 | 编码器接反 | 交换A/B线或软件取反 |
| RPM计算错误 | PPR设置不对 | 手工旋转一周，计数增加值 = PPR |

### 转速不一致

```bash
# 校准步骤：
1. 所有电机设置500 (中等功率)
2. 读取各电机RPM，记录数据
3. 计算补偿系数: factor = baseline_rpm / motor_rpm

示例：
Motor 0: 240 RPM → factor = 240/240 = 1.00
Motor 1: 250 RPM → factor = 240/250 = 0.96
Motor 2: 235 RPM → factor = 240/235 = 1.02
Motor 3: 245 RPM → factor = 240/245 = 0.98

4. 写入补偿：
> C 0 100  (100 = 1.00x)
> C 1 96   (96 = 0.96x)
> C 2 102
> C 3 98
```

### 电机启动困难

```bash
## 症状：需要 > 50% PWM 才能启动

原因排查：
1. 电源电压下降？→ 检查12V是否 < 10.5V
2. 轴承卡死？→ 手转电机，感受摩擦
3. 减速器问题？→ 运行无负载测试（去掉底盘）
4. 驱动芯片故障？→ 更换L298N

快速诊断命令：
> M 0 100  (10%功率)
> M 0 200  (20%功率)
如果 100-300 不动，300-500 才转，说明启动电压偏高
   → 降低 MOTOR_ZERO_DEADBAND (motor_test.c L27)
   → 或增加 MOTOR_PWM_MIN_EFFECTIVE_COUNTS (motor_test_config.h)
```

---

## 🔧 常用命令速查表

```bash
# 电机控制
M <id> <duty>          # 设置电机速度 (id:0-3, duty:-1000~1000)
S                      # 停止所有电机
X                      # 紧急停止（断开驱动器）

# 编码器反馈
E <id>                 # 读取单个编码器
R <id>                 # 重置编码器计数
R all                  # 重置所有编码器计数

# 校准与诊断
C <id> <factor>        # 设置速度补偿系数 (factor: 50-200, 代表 0.5x-2.0x)
P <id> <ppr>          # 设置编码器PPR (例: P 0 20)
D <id>                # 诊断信息

# 自动测试（仅上位机工具）
T [duration]          # 同步性测试 (默认5秒)
A [motor_id]          # 加速度测试 (默认电机0)

# 帮助
H 或 ?                # 显示所有命令

# 例子
M 0 500               # 电机0 -> 50% 前进
M 1 -300              # 电机1 -> 30% 反向
M 2 750               # 电机2 -> 75% 前进
E 3                   # 查看电机3的编码器：count=2500 rpm=120
C 1 95                # 电机1速度补偿到0.95倍
```

---

## 📈 验证检查清单

### ✅ 硬件验收

- [ ] 4个电机能独立正反运转
- [ ] 每个电机转速符合预期（无负载 > 150 RPM @ 50%功率）
- [ ] 编码器能正确计数（单电机转动，数值单调递增/递减）
- [ ] 4电机转速一致性 > 95% (最大偏差 < 5 RPM)
- [ ] 通电后无异味、无发烫（可连续运行 > 10分钟）
- [ ] UART通信正常，响应 < 100ms

### ✅ 性能目标

| 指标 | 预期值 | 实测值 | 通过 |
|------|--------|--------|------|
| 无负载启动响应 | < 100ms | ___ | [ ] |
| 最大转速（满功率12V) | > 200 RPM | ___ | [ ] |
| 编码器精度 | ± 1个脉冲 | ___ | [ ] |
| 四电机同步误差 | < 5% | ___ | [ ] |
| 功率线性度 | ±5% | ___ | [ ] |

### ✅ 可靠性测试

```bash
# 连续运行稳定性（30分钟）
python3 tools/motor_test_tool.py --test

期望：
- 无电机突然停止
- 无编码器计数异常
- 无UART通信中断
- 驱动模块温度正常 (手摸温温的)
```

---

## 问题速查

### Q: 编译错误 "motor_test.h: No such file or directory"
A: 确保 motor_test.h 在 `Core/Inc/` 目录，并检查STM32CubeIDE的 Include Paths 配置。

### Q: 电机转起来但编码器不计数
A: 检查编码器接线（PA0/PA1），确认TIM2启用QEI模式。尝试手动旋转电机。

### Q: UART收不到命令反馈
A: 
1. 检查波特率（应为115200）
2. 检查TX/RX线有没有接反
3. 用示波器确认TX线有信号输出
4. 尝试手动输入 'H' 测试

### Q: 四电机转速不同步
A: 这是正常的（电机参数散差），使用 `C <id> <factor>` 命令进行补偿校准。

### Q: 长时间运行后电机减速或停止
A: 可能是：
1. 12V电源下降 → 检查电源容量和连接
2. 驱动芯片进入热保护 → 降低占空比或增加散热
3. 编码器反馈丢失 → 检查编码器线是否有松动

---

## 📚 深度阅读

想要了解更多细节？
- **软件实现**：查看 `firmware/.../Core/Src/motor_test.c`
- **硬件设计**：查看 `docs/硬件接线与故障排查详细指南.md`
- **完整方案**：查看 `docs/底盘电机驱动独立测试方案.md`

---

## 🎓 下一步

测试通过后，集成到完整系统：

```
✓ 独立电机测试 (本方案)
    ↓
□ 麦轮底盘运动学测试
    ↓
□ 集成视觉模块（camera_test_launch.py）
    ↓
□ 集成云台控制（gimbal_test_launch.py）
    ↓
□ 自动视觉跟随系统（visual_follower_node.py）
```

---

## 📞 技术支持

遇到问题？按这个顺序排查：
1. 查看本文件的"问题速查"部分
2. 查看 `docs/硬件接线与故障排查详细指南.md`
3. 检查 `firmware/.../Core/Src/motor_test.c` 中的注释
4. 启用 STM32 的调试功能（打断点、查看寄存器值）

---

**版本**: 1.0  
**日期**: 2026-04-09  
**作者**: MyDroid 测试方案  
**许可**: Apache 2.0

---

## 变更日志

- **v1.0** (2026-04-09): 初始版本，包含完整测试框架和文档
