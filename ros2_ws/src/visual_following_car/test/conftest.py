"""pytest 公共夹具与测试环境准备。

本文件主要做两件事：

1. 把当前 ROS2 Python 包根目录加入 `sys.path`
   - 这样即使还没有执行 `colcon build` 或 `pip install`，
     我们也可以直接在源码目录里运行 `pytest`。
2. 提供一个复用型 `ros_context` 夹具
   - 只有需要实例化 `rclpy.Node` 的测试才会用到它；
   - 不依赖 ROS2 的纯数学/纯协议测试不会被它拖慢。

这样拆分后，测试层次会更清晰：
- 第一层：纯函数测试，执行最快；
- 第二层：ROS2 节点级测试，需要最小 ROS 上下文；
- 第三层：真实硬件联调，不放在 pytest 里做。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# 把包根目录加入 sys.path，便于直接运行 pytest 时导入源码。
# 例如在 `ros2_ws/src/visual_following_car` 下直接执行：
#     pytest .\test\test_common.py
# 也能成功导入 `visual_following_car.common`。
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


@pytest.fixture
def ros_context():
    """提供一个最小 ROS2 上下文。

    用法：
    - 在需要实例化 `rclpy.Node` 子类的测试中，把此夹具作为参数传入。
    - 测试结束后，如果本夹具负责初始化 ROS，则也会负责关闭 ROS。

    这样做的好处是：
    - 避免每个测试文件重复写 `rclpy.init()` / `rclpy.shutdown()`；
    - 避免多个测试之间因为上下文没有清理干净而互相影响。
    """
    rclpy = pytest.importorskip('rclpy')

    started_here = False
    if not rclpy.ok():
        rclpy.init()
        started_here = True

    yield rclpy

    if started_here and rclpy.ok():
        rclpy.shutdown()
