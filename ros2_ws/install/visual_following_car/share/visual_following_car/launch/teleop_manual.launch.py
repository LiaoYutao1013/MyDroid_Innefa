#!/usr/bin/env python3
"""手动模式调试启动文件。

用途说明：
1. 启动 joy_node。
2. 启动手柄遥控节点。
3. 启动串口桥节点。

这个启动文件不会启动 YOLO 检测和视觉跟随，
因此适合做如下工作：
- 只检查蓝牙手柄映射是否正确。
- 只检查底盘和 Pan 云台手动控制是否正确。
- 不希望视觉节点参与时的基础联调。
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成手动模式下的启动描述。"""
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_following_car.yaml'

    config_file = LaunchConfiguration('config_file')
    joy_dev = LaunchConfiguration('joy_dev')
    serial_port = LaunchConfiguration('serial_port')

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('joy_dev', default_value='/dev/input/js0'),
        DeclareLaunchArgument('serial_port', default_value='/dev/ttyS1'),

        Node(
            package='joy',
            executable='joy_node',
            name='joy_node',
            output='screen',
            parameters=[config_file, {'dev': joy_dev}],
        ),
        Node(
            package='visual_following_car',
            executable='joy_teleop_node',
            name='joy_teleop_node',
            output='screen',
            parameters=[config_file, {'start_in_auto_mode': False}],
        ),
        Node(
            package='visual_following_car',
            executable='serial_bridge_node',
            name='serial_bridge_node',
            output='screen',
            parameters=[config_file, {'port': serial_port}],
        ),
    ])