# Radxa ROCK 3B 蓝牙连接与调试完整指南

## 目录

1. [蓝牙硬件配置](#1-蓝牙硬件配置)
2. [Radxa蓝牙模块启动](#2-radxa蓝牙模块启动)
3. [蓝牙手柄配对](#3-蓝牙手柄配对)
4. [ROS2蓝牙手柄驱动](#4-ros2蓝牙手柄驱动)
5. [手柄映射与适配](#5-手柄映射与适配)
6. [故障排查与诊断](#6-故障排查与诊断)
7. [完整联调流程](#7-完整联调流程)

---

## 1. 蓝牙硬件配置

### 1.1 Radxa ROCK 3B 蓝牙模块

**标准配置**：
- **蓝牙芯片**: RTL8723BU / RTL8852BU（确切型号见下方检查）
- **蓝牙版本**: Bluetooth 5.0 / 5.1
- **工作频率**: 2.4GHz
- **通信距离**: 10-100米（取决于环保境）

**预置支持**：
- ✓ Bluetooth Classic (传统蓝牙，游戏手柄用)
- ✓ Bluetooth Low Energy (BLE，低功耗)

### 1.2 确认蓝牙模块状态

```bash
# 检查蓝牙设备是否被识别
lsusb | grep -i bluetooth
# 输出示例: ID 0bda:8723 Realtek Semiconductor Corp. RTL8723BU

# 或用另一种方法
dmesg | grep -i bluetooth | tail -20

# 查看蓝牙接口
hciconfig
# 输出示例:
# hci0:	Type: Primary  Bus: USB
#     BD Address: 12:34:56:78:9A:BC  ACL MTU: 1021:5  SCO MTU: 64:1
#     UP RUNNING 
#     RX bytes:1234 acl:0 sco:0 evt:345 ERR:0 RX errors:0
#     TX bytes:5678 acl:0 sco:0 cmd:345 ERR:0

# 查看蓝牙服务状态
sudo systemctl status bluetooth
# 应该显示 "active (running)"
```

**如果蓝牙未启用**：

```bash
# 方法1: 启动蓝牙守护进程
sudo systemctl start bluetooth
sudo systemctl enable bluetooth  # 开机自启

# 方法2: 手动启动
sudo bluetoothctl

# 在bluetoothctl提示符下:
> power on
> show
# 应该看到 "Powered: yes"
```

---

## 2. Radxa蓝牙模块启动

### 2.1 Bluetoothctl 基础命令

```bash
# 启动蓝牙控制工具
sudo bluetoothctl

# 在 [bluetooth]# 提示符下，常用命令：

power on                 # 启用蓝牙
power off                # 关闭蓝牙
show                     # 显示蓝牙信息
agent on                 # 启用配对代理
default-agent            # 设置默认代理
discoverable on          # 使ROCK 3B可被发现
discoverable off         # 禁用被发现
scan on                  # 扫描周围蓝牙设备
scan off                 # 停止扫描
devices                  # 列出已发现的设备
pair <MAC>               # 配对指定MAC地址的设备
trust <MAC>              # 信任设备
connect <MAC>            # 连接设备
disconnect <MAC>         # 断开连接
remove <MAC>             # 删除设备记录
info <MAC>               # 显示设备信息
quit                     # 退出
```

### 2.2 蓝牙模块初始化脚本

建议创建一个自动化脚本，开机时自动启用蓝牙：

```bash
cat > ~/init_bluetooth.sh << 'EOF'
#!/bin/bash

# Radxa ROCK 3B 蓝牙初始化脚本

echo "=== Initializing Bluetooth ==="

# 1. 启动蓝牙服务
sudo systemctl start bluetooth
sudo systemctl enable bluetooth

# 2. 启用蓝牙电源
sudo bluetoothctl << 'HEREDOC'
power on
agent on
default-agent
exit
HEREDOC

# 3. 等待蓝牙初始化
sleep 2

# 4. 检查状态
echo "=== Bluetooth Status ==="
hciconfig
echo ""
echo "=== Bluetooth Info ==="
sudo bluetoothctl show

echo "✓ Bluetooth initialized successfully"
EOF

chmod +x ~/init_bluetooth.sh

# 运行脚本
~/init_bluetooth.sh

# 可选：加入开机自启
echo "@reboot ~/init_bluetooth.sh" | crontab -
```

### 2.3 验证蓝牙就绪

```bash
# 完整检查清单
echo "=== Bluetooth Readiness Check ==="

# 检查蓝牙服务运行状态
sudo systemctl is-active bluetooth && echo "✓ Bluetooth service running" || echo "✗ Service not running"

# 检查蓝牙设备可见
hciconfig | grep -q "UP RUNNING" && echo "✓ Bluetooth device UP" || echo "✗ Device not UP"

# 检查蓝牙地址
BTADDR=$(hciconfig | grep "BD Address" | awk '{print $NF}')
echo "✓ Bluetooth MAC: $BTADDR"

# 列出已配对设备
echo ""
echo "=== Paired Devices ==="
sudo bluetoothctl paired-devices
```

---

## 3. 蓝牙手柄配对

### 3.1 雷神蓝牙手柄配对步骤

**硬件准备**：
- 雷神手柄（确保电池有电）
- Radxa ROCK 3B（蓝牙已启用）

**配对步骤**：

```bash
# 第1步：进入蓝牙控制
sudo bluetoothctl

# 第2步：在 [bluetooth]# 提示符下执行

# 启用配对模式（如果还没启用）
power on
agent on
default-agent

# 第3步：启用扫描，寻找手柄
scan on

# 第4步：在你的雷神手柄上，通常需要按住以下按键进入配对模式：
# - 通常是同时按"HOME键"和"X键"保持3-5秒
# - 直到手柄LED闪烁
# - 或按配对键（可能在手柄顶部或底部）

# 第5步：在扫描输出中查找你的手柄
# 输出示例：
# [CHG] Device 5C:F3:70:8A:XX:XX BluetoothController name: Thunderobot_Gamepad
# [CHG] Device 5C:F3:70:8A:XX:XX Connected: yes

# 记下手柄的MAC地址（例如：5C:F3:70:8A:XX:XX）

# 第6步：配对
pair 5C:F3:70:8A:XX:XX

# 系统会询问是否信任，输入
trust 5C:F3:70:8A:XX:XX

# 第7步：连接
connect 5C:F3:70:8A:XX:XX

# 第8步：验证连接
info 5C:F3:70:8A:XX:XX
# 应该看到 "Connected: yes"

# 第9步：停止扫描并退出
scan off
quit
```

### 3.2 自动连接脚本

创建一个脚本，在启动时自动连接已配对的手柄：

```bash
cat > ~/connect_gamepad.sh << 'EOF'
#!/bin/bash

# 雷神手柄自动连接脚本
# 用法: ./connect_gamepad.sh <手柄MAC地址>

GAMEPAD_MAC="${1:-5C:F3:70:8A:XX:XX}"  # 替换为你的手柄MAC

echo "Connecting to Gamepad: $GAMEPAD_MAC"

sudo bluetoothctl << HEREDOC
power on
agent on
default-agent
connect $GAMEPAD_MAC
quit
HEREDOC

# 等待连接完成
sleep 3

# 检查是否连接成功
if sudo bluetoothctl info $GAMEPAD_MAC | grep -q "Connected: yes"; then
    echo "✓ Gamepad connected successfully"
    exit 0
else
    echo "✗ Failed to connect gamepad"
    exit 1
fi
EOF

chmod +x ~/connect_gamepad.sh

# 使用示例
~/connect_gamepad.sh 5C:F3:70:8A:XX:XX
```

### 3.3 查询你的手柄MAC地址

如果你不知道手柄的MAC地址：

```bash
# 方法1: 通过bluetoothctl扫描获取
sudo bluetoothctl scan on
# 让手柄进入配对模式
# 等待看到你的手柄信息，记下MAC地址

# 方法2: 查看已配对设备
sudo bluetoothctl paired-devices
# 输出示例:
# Device 5C:F3:70:8A:12:34 Thunderobot_Gamepad
# Device XX:XX:XX:XX:XX:XX SomeOtherDevice

# 方法3: 从系统日志查找
dmesg | grep -i "thunderobot\|gamepad" | tail -10

# 方法4: 查看配对列表文件
ls -la ~/.local/share/bluez/*/info/
cat ~/.local/share/bluez/*/info/* | grep Address
```

---

## 4. ROS2蓝牙手柄驱动

### 4.1 安装蓝牙手柄驱动

ROS2中使用标准的 `joy` 节点来处理游戏手柄：

```bash
# 安装joy驱动
sudo apt-get install ros-humble-joy

# 如果编译，可以从源代码安装：
cd ~/MyDroid/ros2_ws/src
git clone https://github.com/ros-drivers/joystick_drivers.git
cd ..
colcon build --packages-select joy
```

### 4.2 Joy节点配置

在你的ROS2包中创建joy节点启动配置：

```bash
mkdir -p ros2_ws/src/visual_following_car/launch
mkdir -p ros2_ws/src/visual_following_car/config

# 创建Joy参数文件
cat > ros2_ws/src/visual_following_car/config/joy_params.yaml << 'EOF'
joy_node:
  ros__parameters:
    device_id: 0                    # 蓝牙手柄设备ID (通常为0)
    deadzone: 0.1                   # 死区 (摇杆中心的无反应区域)
    autorepeat_rate: 20.0           # 消息发布频率 (Hz)
    coalesce_interval_ms: 20        # 消息合并间隔 (ms)
    default_trig_val: false         # 触发器默认值
EOF

# 创建Joy启动文件
cat > ros2_ws/src/visual_following_car/launch/joy_launch.py << 'EOF'
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration
import os
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    config_dir = get_package_share_directory('visual_following_car')
    params_file = os.path.join(config_dir, 'config', 'joy_params.yaml')
    
    return LaunchDescription([
        Node(
            package='joy',
            executable='joy_node',
            parameters=[params_file],
            output='screen'
        ),
    ])
EOF
```

### 4.3 验证蓝牙手柄输入

```bash
# 终端1: 启动joy节点
cd ~/MyDroid/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 run joy joy_node

# 终端2: 查看手柄输入
ros2 topic echo /joy

# 应该看到类似输出 (按动手柄时更新):
# axes: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]  # 模拟摇杆和触发器
# buttons: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]  # 按键状态

# 测试: 按手柄上的按键，应该看到buttons数组改变
# 移动摇杆，应该看到axes数组改变
```

---

## 5. 手柄映射与适配

### 5.1 标准Gamepad按键映射

不同品牌的手柄可能有不同的按键索引。标准Xbox/PS4兼容手柄的映射：

```
按键名称                  按键索引 (buttons数组)
────────────────────────────────────
A / Cross (X)             0
B / Circle (O)            1
X / Square (□)            2
Y / Triangle (△)          3
LB / L1                    4
RB / R1                    5
Back / Select             6
Start                     7
Left Stick Click          8
Right Stick Click         9
Guide / Home / PS         10
```

```
摇杆和触发器              轴索引 (axes数组)
────────────────────────────────────
Left Stick X (左右)       0
Left Stick Y (上下)       1
LT (左触发器)             2
Right Stick X (左右)      3
Right Stick Y (上下)      4
RT (右触发器)             5
D-Pad X (左右)            6
D-Pad Y (上下)            7
```

### 5.2 雷神手柄特定映射

对于雷神蓝牙手柄，可能需要特定的映射。首先检测你的手柄映射：

```bash
# 创建手柄映射检测脚本
cat > ~/detect_gamepad_mapping.py << 'EOF'
#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Joy
from rclpy.qos import QoSProfile, QoSReliabilityPolicy

class GamepadDetector(Node):
    def __init__(self):
        super().__init__('gamepad_detector')
        
        qos_profile = QoSProfile(depth=10)
        qos_profile.reliability = QoSReliabilityPolicy.BEST_EFFORT
        
        self.subscription = self.create_subscription(
            Joy,
            '/joy',
            self.joy_callback,
            qos_profile
        )
        self.get_logger().info("按动手柄上的每个按键和摇杆...")
        
    def joy_callback(self, msg):
        print("\n=== Gamepad Input ===")
        print(f"按键 (buttons): {msg.buttons}")
        print(f"轴   (axes):    {[f'{x:.2f}' for x in msg.axes]}")
        
        # 检测按键
        for i, btn in enumerate(msg.buttons):
            if btn == 1:
                print(f"  → 按键 #{i} 被按下")
        
        # 检测轴
        for i, axis in enumerate(msg.axes):
            if abs(axis) > 0.5:
                print(f"  → 轴 #{i} = {axis:.2f}")

def main(args=None):
    rclpy.init(args=args)
    detector = GamepadDetector()
    rclpy.spin(detector)
    rclpy.shutdown()

if __name__ == '__main__':
    main()
EOF

chmod +x ~/detect_gamepad_mapping.py

# 运行检测脚本
cd ~/MyDroid/ros2_ws
source install/setup.bash
python3 ~/detect_gamepad_mapping.py
```

**使用步骤**：
1. 在一个终端启动joy节点
2. 在另一个终端运行上述脚本
3. 按下手柄上的每个按键，记录显示的按键索引
4. 移动每个摇杆和触发器，记录显示的轴索引
5. 根据检测结果调整下方的映射配置

### 5.3 创建手柄映射配置文件

```bash
cat > ~/MyDroid/ros2_ws/src/visual_following_car/config/gamepad_mapping.yaml << 'EOF'
# 雷神蓝牙手柄的按键和轴映射
# 根据你的手柄检测结果修改这些值

gamepad_mapping:
  # 按键映射 (buttons数组的索引)
  buttons:
    A:          0        # A按键 (通常是X/Cross)
    B:          1        # B按键 (通常是O/Circle)
    X:          2        # X按键 (通常是□/Square)
    Y:          3        # Y按键 (通常是△/Triangle)
    LB:         4        # LB按键 (左肩)
    RB:         5        # RB按键 (右肩)
    back:       6        # 返回/选择按键
    start:      7        # 开始按键
    left_stick: 8        # 左摇杆点击
    right_stick:9        # 右摇杆点击
    guide:      10       # HOME/指南按键
  
  # 轴映射 (axes数组的索引)
  axes:
    left_stick_x:  0     # 左摇杆 X轴 (左右)
    left_stick_y:  1     # 左摇杆 Y轴 (上下)
    left_trigger:  2     # 左触发器
    right_stick_x: 3     # 右摇杆 X轴 (左右)
    right_stick_y: 4     # 右摇杆 Y轴 (上下)
    right_trigger: 5     # 右触发器
    dpad_x:        6     # D-Pad X轴 (左右)
    dpad_y:        7     # D-Pad Y轴 (上下)

  # 控制映射 (摇杆对应的功能)
  controls:
    # 底盘控制
    forward:     "left_stick_y"   # 前进/后退
    strafe:      "left_stick_x"   # 左平移/右平移
    rotate:      "right_stick_x"  # 左旋转/右旋转
    
    # 功能按键
    enable:      "start"          # 启用自动跟随
    disable:     "back"           # 禁用自动跟随
    gimbal_up:   "left_trigger"   # 云台上转
    gimbal_down: "right_trigger"  # 云台下转
    estop:       "Y"              # 紧急停止
EOF
```

---

## 6. 故障排查与诊断

### 6.1 常见蓝牙连接问题

| 现象 | 原因 | 解决方案 |
|------|------|--------|
| 找不到手柄 | 手柄未进入配对模式 | 按手柄上的配对键3-5秒 |
| 无法配对 | 蓝牙服务未启动 | 运行 `sudo systemctl start bluetooth` |
| 配对成功但连接失败 | 驱动问题或信号干扰 | 重启蓝牙：`sudo systemctl restart bluetooth` |
| 手柄断连频繁 | 距离太远或干扰 | 靠近ROCK 3B，避免WiFi干扰 |
| Joy节点收不到输入 | 设备ID错误 | 检查 `ls /dev/input/js*` 找到正确设备 |
| 按键映射错乱 | 按键索引不对 | 运行映射检测脚本重新确配 |

### 6.2 调试命令集

```bash
# 完整的蓝牙诊断流程
echo "=== Step 1: Check Bluetooth Service ==="
sudo systemctl status bluetooth

echo ""
echo "=== Step 2: Check Bluetooth Device ==="
hciconfig

echo ""
echo "=== Step 3: Check Connected Devices ==="
sudo bluetoothctl connected-devices

echo ""
echo "=== Step 4: Check Joy Node Status ==="
ros2 node list | grep joy

echo ""
echo "=== Step 5: Check Joy Input ==="
timeout 5 ros2 topic echo /joy || true

echo ""
echo "=== Step 6: Check Input Device ==="
ls -la /dev/input/js*

echo ""
echo "=== Step 7: Test Direct Input (if jstest installed) ==="
which jstest && jstest /dev/input/js0 || echo "jstest not installed"
```

### 6.3 蓝牙连接故障排查树

```
蓝牙手柄无法连接？
├─ 蓝牙服务运行吗?
│  ├─ 否 → sudo systemctl start bluetooth
│  └─ 是 → [继续]
│
├─ 手柄进入配对模式了吗?
│  ├─ 否 → 按手柄上的配对键
│  └─ 是 → [继续]
│
├─ 手柄在配对列表中吗?
│  ├─ 否 → sudo bluetoothctl scan on 重新扫描
│  └─ 是 → [继续]
│
├─ 蓝牙信号强度足够吗?
│  ├─ 否 → 靠近ROCK 3B
│  └─ 是 → [继续]
│
└─ 尝试重启蓝牙
   └─ sudo systemctl restart bluetooth
      再试 ~/connect_gamepad.sh <MAC>
```

### 6.4 Joy节点故障排查

```bash
# 检查joy节点是否启动
ps aux | grep joy

# 查看joy节点日志
ros2 run joy joy_node --ros-args --log-level debug

# 查看输入设备
cat /proc/bus/input/devices | grep -A 5 "js"

# 直接读取输入
sudo evtest /dev/input/event* # 选择对应的event设备

# 查看当前ROS网络
ros2 topic list
ros2 topic info /joy
```

---

## 7. 完整联调流程

### 7.1 蓝牙→ROCK 3B→STM32控制流程

```
蓝牙手柄 (雷神) 
  ↓ (蓝牙HCI协议)
ROCK 3B (Joy节点)
  ↓ (ROS2 /joy 消息)
游戏手柄处理节点 (joy_teleop_node)
  ↓ (ROS2 /cmd_vel 消息)
串口桥接节点 (serial_bridge_node)
  ↓ (UART 16字节固定帧)
STM32F407 (USART1接收)
  ↓ (协议解析)
电机驱动层 (motor_control.c)
  ↓ (PWM + GPIO输出)
L298N驱动模块 → 520电机
```

### 7.2 分步联调

**第1步: 蓝牙连接和Joy输入**

```bash
# 终端1: 启动Joy节点
cd ~/MyDroid/ros2_ws
source install/setup.bash
ros2 run joy joy_node --ros-args --log-level info

# 终端2: 监听Joy消息
ros2 topic echo /joy --field buttons --field axes --once

# 期望: 看到手柄按键和摇杆的数值变化
```

**第2步: 手柄→速度命令映射**

```bash
# 让joy_teleop_node运行（如果有的话），或启动新的手柄处理节点
ros2 run visual_following_car joy_teleop_node

# 终端: 监听速度命令
ros2 topic echo /cmd_vel

# 期望: 移动摇杆时，看到 linear.x / linear.y / angular.z 的值变化
```

**第3步: 速度命令→UART帧**

```bash
# 启动串口桥接
ros2 run visual_following_car serial_bridge_node --ros-args --log-level debug

# 发送速度命令
ros2 topic pub /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}, angular: {z: 0}}"

# 用示波器或串口监视器查看UART输出
screen /dev/ttyS1 115200
# 或读取日志看 "Sending frame..."
```

**第4步: 完整集成联调**

```bash
# 运行完整系统
cd ~/MyDroid/ros2_ws
source install/setup.bash

# 启动所有模块
ros2 launch visual_following_car teleop_manual.launch.py

# 此时应该能用蓝牙手柄控制底盘
```

### 7.3 验收检查清单

```
□ 蓝牙手柄能配对到ROCK 3B
□ Joy节点能接收手柄输入
□ /joy 话题有实时更新
□ joy_teleop_node能将Joy消息转为Twist
□ /cmd_vel 话题有速度命令输出
□ serial_bridge_node正确编码UART帧
□ STM32正确接收和解析帧
□ 电机按照手柄输入运转
□ 手柄按键功能正确映射
```

---

## 8. 高级配置

### 8.1 自定义手柄处理节点模板

见后续的代码部分中的 `bluetooth_gamepad_node.py`

### 8.2 死区调整

在joy_params.yaml中调整：
```yaml
deadzone: 0.1  # 增加值以增加死区，避免漂移
```

### 8.3 多手柄支持

如果需要多个手柄：
```bash
# 检查所有输入设备
ls /dev/input/js*

# 在joy节点中指定设备
device_id: 0  # 第一个手柄
device_id: 1  # 第二个手柄
```

---

## 9. 快速参考

### 蓝牙操作速查表

| 操作 | 命令 |
|------|------|
| 启动蓝牙 | `sudo systemctl start bluetooth` |
| 进入蓝牙控制 | `sudo bluetoothctl` |
| 扫描设备 | `scan on` (bluetoothctl中) |
| 配对 | `pair <MAC>` (bluetoothctl中) |
| 连接 | `connect <MAC>` (bluetoothctl中) |
| 查看已连接 | `sudo bluetoothctl connected-devices` |
| 启动Joy节点 | `ros2 run joy joy_node` |
| 查看Joy输入 | `ros2 topic echo /joy` |
| 检测按键映射 | `python3 ~/detect_gamepad_mapping.py` |

---

**下一步**: 查看 ROS2蓝牙手柄处理节点代码部分
