#!/usr/bin/env python3
"""
蓝牙手柄按键和轴映射检测脚本

用途：
  1. 检测你的蓝牙手柄的按键索引
  2. 检测各个轴的索引
  3. 根据检测结果生成合适的映射配置

使用方法：
  python3 detect_gamepad_mapping.py

  然后按下手柄上的每个按键和移动摇杆，观察输出
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Joy
import time


class GamepadMappingDetector(Node):
    def __init__(self):
        super().__init__('gamepad_mapping_detector')

        qos_profile = QoSProfile(depth=10)
        qos_profile.reliability = QoSReliabilityPolicy.BEST_EFFORT

        self.subscription = self.create_subscription(
            Joy,
            '/joy',
            self.joy_callback,
            qos_profile
        )

        self.button_names = {}
        self.axis_names = {}
        self.last_buttons = None
        self.last_axes = None

        print("\n" + "=" * 60)
        print("手柄按键和轴映射检测工具")
        print("=" * 60)
        print("\n请按照以下步骤操作：")
        print("  1. 按下手柄上的每一个按键（一个一个来）")
        print("  2. 移动手柄上的每一个模拟摇杆（上下左右各测）")
        print("  3. 按下手柄上的触发器")
        print("  4. 按方向键（D-Pad）")
        print("\n工具将显示按键/轴的索引和值")
        print("=" * 60 + "\n")

        self.get_logger().info("等待Joy消息... 请操作你的手柄")
        self.start_time = time.time()

    def joy_callback(self, msg: Joy):
        """处理Joy消息"""

        # 检查按键变化
        if self.last_buttons != msg.buttons:
            self._detect_buttons(msg.buttons)
            self.last_buttons = list(msg.buttons)

        # 检查轴变化
        if self.last_axes != msg.axes:
            self._detect_axes(msg.axes)
            self.last_axes = list(msg.axes)

    def _detect_buttons(self, buttons):
        """检查按键变化"""
        for i, btn in enumerate(buttons):
            if btn == 1:
                if i not in self.button_names:
                    # 询问用户这个按键是什么
                    print(f"\n>>> 检测到按键 #{i} 被按下")
                    print(f"这是哪个按键？请输入（A/B/X/Y/LB/RB/Back/Start/LS/RS/Guide）:")
                    try:
                        name = input("  输入按键名称: ").strip()
                        if name:
                            self.button_names[i] = name
                            print(f"✓ 按键 #{i} = {name}")
                            self._save_mapping()
                    except:
                        pass

    def _detect_axes(self, axes):
        """检查轴变化"""
        for i, val in enumerate(axes):
            if abs(val) > 0.5:  # 只检测有意义的轴值（大于50%）
                if i not in self.axis_names:
                    print(f"\n>>> 检测到轴 #{i} 有输入: {val:.2f}")
                    print(f"这是哪个轴？请输入（LX/LY/LT/RX/RY/RT/DX/DY）:")
                    try:
                        name = input("  输入轴名称: ").strip()
                        if name:
                            self.axis_names[i] = name
                            print(f"✓ 轴 #{i} = {name}")
                            self._save_mapping()
                    except:
                        pass

    def _save_mapping(self):
        """保存当前的映射"""
        print("\n当前映射汇总:")
        print("-" * 40)

        if self.button_names:
            print("按键映射:")
            for idx, name in sorted(self.button_names.items()):
                print(f"  {idx:2d} → {name}")

        if self.axis_names:
            print("\n轴映射:")
            for idx, name in sorted(self.axis_names.items()):
                print(f"  {idx:2d} → {name}")

        print("-" * 40)
        print("\n注意：复制上述映射到 gamepad_mapping.yaml中")


def main(args=None):
    rclpy.init(args=args)
    detector = GamepadMappingDetector()

    try:
        rclpy.spin(detector)
    except KeyboardInterrupt:
        print("\n\n检测完成！")
        print("\n" + "=" * 60)
        print("检测结果汇总")
        print("=" * 60)
        if detector.button_names or detector.axis_names:
            print("\n请将以下内容复制到 gamepad_mapping.yaml:")
            print("\ngamepad_mapping:")
            print("  buttons:")
            for idx, name in sorted(detector.button_names.items()):
                print(f"    {name:20s}: {idx}")
            print("\n  axes:")
            for idx, name in sorted(detector.axis_names.items()):
                print(f"    {name:20s}: {idx}")
        else:
            print("\n未检测到任何输入。请检查:")
            print("  1. Joy节点是否运行？")
            print("  2. 手柄是否连接？")
            print("  3. 手柄是否有输入？")
        print("=" * 60 + "\n")
    finally:
        detector.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
