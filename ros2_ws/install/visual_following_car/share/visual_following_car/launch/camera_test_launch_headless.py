#!/usr/bin/env python3
"""USB 摄像头 + YOLO + 视觉跟随的纯视觉测试启动文件（无 GUI 版本）。

改进说明：
1. 移除 rqt_image_view 和 rqt_graph（适用于无图形界面的环境）
2. 启用实时日志输出便于调试
3. 可选 mock_serial_bridge 用于测试，或直接使用真实串口桥

用途说明：
1. 启动 usb_cam 官方节点采集相机图像。
2. 启动 YOLO 检测节点。
3. 启动视觉跟随控制节点。
4. 启动 mock 串口桥，只打印控制输出，不访问真实串口。
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    """生成纯视觉测试模式的启动描述（无 GUI）。"""
    package_share = get_package_share_directory('visual_following_car')
    default_config = package_share + '/config/visual_follower.yaml'

    config_file = LaunchConfiguration('config_file')
    video_device = LaunchConfiguration('video_device')
    image_width = LaunchConfiguration('image_width')
    image_height = LaunchConfiguration('image_height')
    framerate = LaunchConfiguration('framerate')

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

        # USB 摄像头节点：从 Linux V4L2 采集图像
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

        # YOLO 检测节点：订阅图像并发布目标框
        Node(
            package='visual_following_car',
            executable='yolo_detection_node',
            name='yolo_detection_node',
            output='screen',
            parameters=[config_file],
        ),

        # 视觉跟随节点：根据检测结果计算底盘速度和 Pan 命令
        Node(
            package='visual_following_car',
            executable='visual_follower_node',
            name='visual_follower_node',
            output='screen',
            parameters=[config_file],
        ),

        # Mock 串口桥：只打印计算结果，不访问真实硬件
        # 用于纯视觉功能测试
        Node(
            package='visual_following_car',
            executable='mock_serial_bridge',
            name='mock_serial_bridge',
            output='screen',
            parameters=[config_file],
        ),

        # 注意：以下 GUI 节点已移除（适用于无图形界面的环境）
        # 如果需要图形化调试，请在具有 X11 的机器上单独运行：
        #   ros2 run rqt_image_view rqt_image_view --args /image_raw
        #   ros2 run rqt_graph rqt_graph
    ])
