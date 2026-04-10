"""setuptools 安装入口。

这个文件的作用是告诉 ROS 2 / colcon：
1. 本包的 Python 模块叫什么名字。
2. 哪些 launch/config/resource 文件需要安装到 share 目录。
3. 哪些 Python 脚本要注册成可执行的 ROS 2 节点。
"""

from glob import glob
import os

from setuptools import setup


# ROS 2 包名与 Python 模块名保持一致，便于维护。
package_name = 'visual_following_car'


setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        # ament 索引资源文件，ROS 2 通过它定位包。
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),

        # 安装到 share/<package_name>/ 根目录下的元数据文件。
        ('share/' + package_name, ['package.xml', 'CMakeLists.txt', 'requirements.txt']),

        # 安装全部 launch 文件。
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),

        # 安装全部 YAML 配置文件。
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),

        # 安装模型目录中的文件。
        # 这样后续把 .pt / .onnx / .rknn 放进 models/ 后，重新构建即可一起带入安装目录。
        (os.path.join('share', package_name, 'models'), glob('models/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=False,
    maintainer='MyDroid Developer',
    maintainer_email='you@example.com',
    description='ROS 2 visual following car for ROCK 3B + STM32 mecanum base.',
    license='MIT',
    entry_points={
        'console_scripts': [
            # 下面这些名称会成为 `ros2 run visual_following_car <name>` 可执行入口。
            'joy_teleop_node = visual_following_car.joy_teleop_node:main',
            'yolo_detection_node = visual_following_car.yolo_detection_node:main',
            'visual_follower_node = visual_following_car.visual_follower_node:main',
            'serial_bridge_node = visual_following_car.serial_bridge_node:main',
            'mock_serial_bridge = visual_following_car.mock_serial_bridge:main',
            'screenshot_node = visual_following_car.screenshot_node:main',

            # 蓝牙手柄相关节点 (新增 ★)
            'bluetooth_gamepad_node = visual_following_car.bluetooth_gamepad_node:main',
            'detect_gamepad_mapping = visual_following_car.detect_gamepad_mapping:main',
        ],
    },
)
