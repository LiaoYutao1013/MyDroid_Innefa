from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import LogInfo
import os
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    """
    蓝牙手柄控制启动文件

    启动以下节点：
    1. Joy节点 - 读取蓝牙手柄输入
    2. 蓝牙手柄处理节点 - 将Joy转换为速度命令
    3. 串口桥接节点 - 将ROS2命令发送到STM32
    4. 电机控制节点 - STM32固件执行
    """

    config_dir = get_package_share_directory('visual_following_car')
    joy_params_file = os.path.join(config_dir, 'config', 'joy_params.yaml')

    return LaunchDescription([
        # 日志信息
        LogInfo(msg="┌─ Bluetooth Gamepad Control System"),
        LogInfo(msg="├─ Joy Node (read gamepad input)"),
        LogInfo(msg="├─ Bluetooth Gamepad Node (map input to commands)"),
        LogInfo(msg="├─ Serial Bridge Node (send to STM32)"),
        LogInfo(msg="└─ All systems ready!"),

        # Joy节点 - 读取蓝牙手柄
        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            parameters=[joy_params_file],
            output='screen',
            emulate_tty=True,
        ),

        # 蓝牙手柄处理节点 - 将Joy转为Twist
        Node(
            package='visual_following_car',
            executable='bluetooth_gamepad_node',
            name='bluetooth_gamepad_node',
            output='screen',
            emulate_tty=True,
            parameters=[
                {'max_linear_speed': 0.5},      # 最大线速度 m/s
                {'max_angular_speed': 1.0},     # 最大角速度 rad/s
                {'deadzone': 0.1},              # 摇杆死区
                {'enable_debug': True},         # 启用调试日志
            ]
        ),

        # 串口桥接节点 - 将ROS2命令发送到STM32
        Node(
            package='visual_following_car',
            executable='serial_bridge_node',
            name='serial_bridge_node',
            output='screen',
            emulate_tty=True,
            parameters=[
                {'port': '/dev/ttyS1'},         # UART端口
                {'baudrate': 115200},           # 波特率
                {'timeout': 0.5},               # 读超时（秒）
                {'cmd_timeout': 0.5},           # 命令超时停车（秒）
            ]
        ),
    ])
