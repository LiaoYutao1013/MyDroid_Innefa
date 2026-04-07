#!/usr/bin/env python3
"""Pan 云台单独调试启动文件。

用途说明：
1. 不依赖真实摄像头和 YOLO 节点。
2. 通过手动向 `/vision/target_bbox` 发布测试数据，验证 Pan 控制逻辑。
3. 配合 mock_serial_bridge 观察最终的 `/gimbal_cmd` 输出。
4. 配合 rqt_graph 和 rqt_publisher 快速做参数与话题联调。

适合场景：
- 还没接入真实 STM32 时，先验证视觉跟随的 Pan 算法。
- 只想看“目标 x 坐标变化时，Pan 角度是否按预期变化”。
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成 Pan-only 云台调试的启动描述。"""
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_following_car.yaml'

    config_file = LaunchConfiguration('config_file')

    return LaunchDescription([
        DeclareLaunchArgument('config_file', default_value=default_config),

        # 启动视觉跟随节点，但强制进入 camera_test_mode，避免访问真实串口。
        Node(
            package='visual_following_car',
            executable='visual_follower_node',
            name='visual_follower_node',
            output='screen',
            parameters=[config_file, {
                'camera_test_mode': True,
                'gimbal.pan_enabled': True,
            }],
        ),

        # 启动 mock 串口桥，以便直接看到 Pan 输出值。
        Node(
            package='visual_following_car',
            executable='mock_serial_bridge',
            name='mock_serial_bridge',
            output='screen',
        ),

        # 用于人工构造 vision/target_bbox 消息。
        Node(
            package='rqt_publisher',
            executable='rqt_publisher',
            name='rqt_publisher',
            output='screen',
        ),

        # 查看当前节点和话题连接关系。
        Node(
            package='rqt_graph',
            executable='rqt_graph',
            name='rqt_graph',
            output='screen',
        ),
    ])