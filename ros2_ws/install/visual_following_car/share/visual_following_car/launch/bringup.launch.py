#!/usr/bin/env python3
"""整车 Bringup 启动文件。

用途说明：
1. 启动官方 joy_node，读取蓝牙手柄。
2. 启动手柄遥控节点，把 Joy 转换为底盘和云台命令。
3. 启动 YOLO 目标检测节点。
4. 启动视觉跟随控制节点。
5. 启动串口桥，把 ROS2 控制量发送给 STM32。

适用场景：
- 真机整车联调。
- 需要同时测试视觉、遥控和串口链路时。
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成 LaunchDescription。

    这里使用 LaunchArgument 的原因：
    - 允许用户在命令行覆盖配置文件路径。
    - 允许用户临时切换串口、相机设备或手柄设备。
    """
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_following_car.yaml'

    config_file = LaunchConfiguration('config_file')
    joy_dev = LaunchConfiguration('joy_dev')
    serial_port = LaunchConfiguration('serial_port')
    camera_device = LaunchConfiguration('camera_device')

    return LaunchDescription([
        # 配置文件路径：默认使用包内 YAML，也可在启动时手动指定。
        DeclareLaunchArgument('config_file', default_value=default_config),

        # 手柄设备路径，例如 /dev/input/js0。
        DeclareLaunchArgument('joy_dev', default_value='/dev/input/js0'),

        # ROCK 3B 到 STM32 的串口设备名。
        DeclareLaunchArgument('serial_port', default_value='/dev/ttyS1'),

        # 本地摄像头设备，例如 /dev/video0。
        DeclareLaunchArgument('camera_device', default_value='/dev/video0'),

        # 官方 joy_node：负责把 Linux 手柄事件发布成 sensor_msgs/Joy。
        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            output='screen',
            parameters=[config_file, {'dev': joy_dev}],
        ),

        # 遥控节点：负责解释手柄轴和按键。
        Node(
            package='visual_following_car',
            executable='joy_teleop_node',
            name='joy_teleop_node',
            output='screen',
            parameters=[config_file],
        ),

        # 视觉检测节点：输出目标框和粗略距离。
        Node(
            package='visual_following_car',
            executable='yolo_detection_node',
            name='yolo_detection_node',
            output='screen',
            parameters=[config_file, {'camera_device': camera_device}],
        ),

        # 视觉跟随控制节点：根据目标检测结果输出底盘与云台命令。
        Node(
            package='visual_following_car',
            executable='visual_follower_node',
            name='visual_follower_node',
            output='screen',
            parameters=[config_file],
        ),

        # 串口桥节点：把 ROS2 命令打包发送给 STM32。
        Node(
            package='visual_following_car',
            executable='serial_bridge_node',
            name='serial_bridge_node',
            output='screen',
            parameters=[config_file, {'port': serial_port}],
        ),
    ])