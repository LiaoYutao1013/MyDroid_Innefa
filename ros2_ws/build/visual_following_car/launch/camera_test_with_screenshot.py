#!/usr/bin/env python3
"""USB摄像头+YOLO+视觉跟随+定时截图的完整启动文件。

相比原始版本的改进：
1. 新增 screenshot_node，定时保存带检测框的截图
2. 实时输出检测结果到终端和文件
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成完整的视觉跟随启动描述（含截图）。"""
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_follower.yaml'

    config_file = LaunchConfiguration('config_file')
    video_device = LaunchConfiguration('video_device')
    image_width = LaunchConfiguration('image_width')
    image_height = LaunchConfiguration('image_height')
    framerate = LaunchConfiguration('framerate')
    screenshot_interval = LaunchConfiguration('screenshot_interval')
    screenshot_dir = LaunchConfiguration('screenshot_dir')

    return LaunchDescription([
        # 配置参数
        DeclareLaunchArgument('config_file', default_value=default_config,
                            description='视觉跟随配置文件路径'),
        DeclareLaunchArgument('video_device', default_value='/dev/video0',
                            description='摄像头设备路径'),
        DeclareLaunchArgument('image_width', default_value='640',
                            description='摄像头分辨率宽度'),
        DeclareLaunchArgument('image_height', default_value='480',
                            description='摄像头分辨率高度'),
        DeclareLaunchArgument('framerate', default_value='30.0',
                            description='摄像头帧率'),
        DeclareLaunchArgument('screenshot_interval', default_value='5.0',
                            description='截图时间间隔（秒）'),
        DeclareLaunchArgument('screenshot_dir', default_value='/tmp/mydroid_screenshots',
                            description='截图保存目录'),

        # USB 摄像头节点
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

        # YOLO 检测节点（支持 RKNN RetinaFace）
        Node(
            package='visual_following_car',
            executable='yolo_detection_node',
            name='yolo_detection_node',
            output='screen',
            parameters=[config_file],
        ),

        # 视觉跟随控制节点
        Node(
            package='visual_following_car',
            executable='visual_follower_node',
            name='visual_follower_node',
            output='screen',
            parameters=[config_file],
        ),

        # Mock 串口桥（仅输出，不控制硬件）
        Node(
            package='visual_following_car',
            executable='mock_serial_bridge',
            name='mock_serial_bridge',
            output='screen',
            parameters=[config_file],
        ),

        # ✨ 新增：定时截图节点（含检测结果绘制）
        Node(
            package='visual_following_car',
            executable='screenshot_node',
            name='screenshot_node',
            output='screen',
            parameters=[{
                'image_topic': '/image_raw',
                'detection_topic': 'vision/target_bbox',
                'screenshot_interval_sec': screenshot_interval,
                'output_dir': screenshot_dir,
                'enable_detection_overlay': True,
                'save_video': False,
                'log_terminal': True,
            }],
        ),
    ])
