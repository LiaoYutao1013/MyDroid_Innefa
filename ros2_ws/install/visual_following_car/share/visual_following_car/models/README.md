# 模型目录说明

这个目录建议统一存放视觉跟随项目使用的模型文件，例如：

```text
models/
├── yolov8n.pt
├── yolov8n.onnx
├── yolov8n_rk3568.rknn
└── person_follow_yolov8n_rk3568.rknn
```

## 推荐原因

1. 模型文件和 ROS2 包放在同一个工程里，迁移设备时不容易遗漏。
2. `.pt`、`.onnx`、`.rknn` 可以并排存放，便于做对照测试。
3. 后面改 YAML 参数时，路径结构统一。

## 当前建议

联调初期建议在 YAML 中使用模型的绝对路径，例如：

```yaml
model_path: /home/rock/MyDroid/ros2_ws/src/visual_following_car/models/yolov8n_rk3568.rknn
```

这样做的好处是：

- 不依赖当前工作目录；
- 一眼就能看出模型究竟放在哪；
- 路径问题更容易排查。

## Windows 测试提示

Windows 上做纯视觉验证时，优先使用 `.pt` 或 `.onnx`。  
`.rknn` 更适合在 RK3568 + RKNN Runtime 的目标环境中使用。
