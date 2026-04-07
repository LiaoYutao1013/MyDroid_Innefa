# 摄像头测试启动指南

## 前置条件

1. ✅ 编译已完成
2. ROS2 Humble 已安装
3. 以下包应已安装（如未安装需通过 `apt install` 安装）：
   - `ros-humble-usb-cam`
   - `ros-humble-rqt-image-view`
   - `ros-humble-rqt-graph`

## 快速启动

### 方式 1：完整启动（包含 GUI 工具，需要图形界面）

```bash
# 1. 打开新终端
cd /home/radxa/MyDroid/ros2_ws

# 2. 激活 ROS2 环境
source /opt/ros/humble/setup.bash
source install/setup.bash

# 3. 启动摄像头测试
ros2 launch visual_following_car camera_test_launch.py
```

**输出说明：**
- `usb_cam` 节点：采集摄像头图像，发布到 `/image_raw` 话题
- `yolo_detection_node`：订阅图像，进行目标检测
- `visual_follower_node`：计算 Pan 控制角度
- `mock_serial_bridge`：打印控制输出（不访问真实硬件）
- `rqt_image_view`：显示摄像头实时画面（需要 GUI）
- `rqt_graph`：显示节点依赖关系（需要 GUI）

### 方式 2：仅启动核心节点（无 GUI）

如果主板没有图形界面，编辑 `camera_test_launch.py`，注释掉 GUI 节点：

```python
# 注释掉这两行：
# Node(package='rqt_image_view', ...),
# Node(package='rqt_graph', ...),
```

然后运行同样的命令：

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch visual_following_car camera_test_launch.py
```

### 方式 3：调整参数启动

```bash
ros2 launch visual_following_car camera_test_launch.py \
    video_device:=/dev/video0 \
    image_width:=640 \
    image_height:=480 \
    framerate:=30.0
```

## 调试

### 查看话题列表
```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 topic list
```

### 查看单个话题数据
```bash
ros2 topic echo /image_raw
ros2 topic echo /detections
```

### 查看节点日志
```bash
# 在另一个终端中，启动完全后运行：
ros2 node list                    # 查看所有节点
ros2 node info /usb_cam           # 查看单个节点信息
```

### 命令行杀死所有 ROS2 节点
```bash
ros2 lifecycle kill visual_follower_node
# 或直接按 Ctrl+C
```

## 常见问题

### 1. 找不到摄像头
```
[ERROR] Failed to open camera
```
**解决方案：**
- 检查摄像头是否正确连接：`ls -la /dev/video*`
- 修改参数：`video_device:=/dev/video1` 或其他索引

### 2. 节点启动失败
**检查 ROS2 环境：**
```bash
echo $ROS_DISTRO
echo $AMENT_PREFIX_PATH
```

### 3. 串口报错（mock_serial_bridge）
如果启用了真实串口桥，确保串口权限：
```bash
sudo usermod -a -G dialout $USER
# 重新登录后生效
```

## 下一步

- 修改 `visual_following_car.yaml` 调整跟踪参数
- 连接真实硬件后，更换为 `serial_bridge_node`
- 对接 STM32 下位机的串口协议
