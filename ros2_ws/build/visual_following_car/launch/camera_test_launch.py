#!/usr/bin/env python3
"""USB 摄像头 + YOLO + 视觉跟随的纯视觉测试启动文件。

用途说明：
1. 启动 usb_cam 官方节点采集相机图像。
2. 启动 YOLO 检测节点。
3. 启动视觉跟随控制节点。
4. 启动 mock 串口桥，只打印控制输出，不访问真实串口。
5. 启动 rqt_image_view 和 rqt_graph，便于现场调试。

特别说明：
- 当前项目的节点主体是 rclpy Python 节点，而不是 rclcpp 组件。
- 因此这里采用标准 Node 启动方式，而不是 ComposableNodeContainer。
- 这样做的优点是保持对现有代码侵入最小，适合你当前“只有 ROCK 3B + USB 摄像头”的测试阶段。
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成纯视觉测试模式的启动描述。"""
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_follower.yaml'

    config_file = LaunchConfiguration('config_file')
    video_device = LaunchConfiguration('video_device')
    image_width = LaunchConfiguration('image_width')
    image_height = LaunchConfiguration('image_height')
    framerate = LaunchConfiguration('framerate')

    return LaunchDescription([
        # 使用单独的视觉测试配置，避免误触发真实串口输出。
        DeclareLaunchArgument('config_file', default_value=default_config),
        DeclareLaunchArgument('video_device', default_value='/dev/video0'),
        DeclareLaunchArgument('image_width', default_value='640'),
        DeclareLaunchArgument('image_height', default_value='480'),
        DeclareLaunchArgument('framerate', default_value='30.0'),

        # usb_cam 官方节点：直接从 Linux V4L2 摄像头采集图像。
        Node(
            package='usb_cam',
            executable='usb_cam_node_exe',
            name='usb_cam',
            output='screen',
            parameters=[{
                'video_device': video_device,
                'image_width': ParameterValue(image_width, value_type=int),
                'image_height': ParameterValue(image_height, value_type=int),
                'framerate': ParameterValue(framerate, value_type=float),
                'pixel_format': 'yuyv',
                'camera_frame_id': 'usb_cam',
                'io_method': 'mmap',
                'autofocus': False,
            }],
            remappings=[('image_raw', '/image_raw')],
        ),

        # YOLO 检测节点：订阅图像并发布目标框。
        Node(
            package='visual_following_car',
            executable='yolo_detection_node',
            name='yolo_detection_node',
            output='screen',
            parameters=[config_file],
        ),

        # 视觉跟随节点：根据检测结果计算底盘速度和 Pan 命令。
        Node(
            package='visual_following_car',
            executable='visual_follower_node',
            name='visual_follower_node',
            output='screen',
            parameters=[config_file],
        ),

        # mock 串口桥：只打印计算结果，不实际操作硬件。
        Node(
            package='visual_following_car',
            executable='mock_serial_bridge',
            name='mock_serial_bridge',
            output='screen',
            parameters=[config_file],
        ),

        # 图像查看工具：方便观察摄像头输入画面。
        Node(
            package='rqt_image_view',
            executable='rqt_image_view',
            name='rqt_image_view',
            output='screen',
            arguments=['/image_raw'],
        ),

        # 拓扑图工具：方便检查话题连接关系是否正确。
        Node(
            package='rqt_graph',
            executable='rqt_graph',
            name='rqt_graph',
            output='screen',
        ),
    ])