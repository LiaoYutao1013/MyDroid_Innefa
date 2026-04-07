# MyDroid Visual Following Car

## Project Layout

```text
MyDroid/
|-- firmware/
|   `-- stm32_visual_follower/
|       `-- Core/
|           |-- Inc/
|           |   |-- app_config.h
|           |   |-- main.h
|           |   |-- motor_control.h
|           |   |-- protocol.h
|           |   `-- stm32f4xx_it.h
|           `-- Src/
|               |-- main.c
|               |-- motor_control.c
|               |-- protocol.c
|               `-- stm32f4xx_it.c
`-- ros2_ws/
    `-- src/
        `-- visual_following_car/
            |-- CMakeLists.txt
            |-- package.xml
            |-- requirements.txt
            |-- setup.cfg
            |-- setup.py
            |-- config/
            |   `-- visual_following_car.yaml
            |-- launch/
            |   |-- bringup.launch.py
            |   `-- teleop_manual.launch.py
            |-- resource/
            |   `-- visual_following_car
            `-- visual_following_car/
                |-- __init__.py
                |-- common.py
                |-- joy_teleop_node.py
                |-- serial_bridge_node.py
                |-- visual_follower_node.py
                `-- yolo_detection_node.py
```

## ROS 2 Messages Used

No custom ROS messages are required.

- Chassis velocity: `geometry_msgs/msg/Twist`
- Gimbal command: `std_msgs/msg/Float64MultiArray` with `[pan_deg, tilt_deg]`
- Target bounding box: `std_msgs/msg/Float32MultiArray` with `[cx_norm, cy_norm, w_norm, h_norm, confidence, area_norm, approx_distance_m, image_width, image_height]`
- Auto/manual mode and E-stop: `std_msgs/msg/Bool`

## Serial Protocol

Frame length is fixed at 16 bytes.

| Byte(s) | Field | Type | Unit | Notes |
|---|---|---|---|---|
| 0 | Header 0 | `uint8` | - | `0xAA` |
| 1 | Header 1 | `uint8` | - | `0x55` |
| 2 | Sequence | `uint8` | - | Increments every frame |
| 3 | Flags | `uint8` | bitfield | bit0=`auto`, bit1=`estop`, bit2=`command_valid` |
| 4-5 | `vx` | `int16_le` | mm/s | forward positive |
| 6-7 | `vy` | `int16_le` | mm/s | left positive |
| 8-9 | `omega` | `int16_le` | mrad/s | CCW positive |
| 10-11 | `pan` | `uint16_le` | centi-deg | 0-18000 |
| 12-13 | `tilt` | `uint16_le` | centi-deg | 0-18000 |
| 14-15 | CRC16 | `uint16_le` | - | CRC16-CCITT over bytes `0..13` |

CRC polynomial: `0x1021`, initial value: `0xFFFF`.

## ROCK 3B Setup

1. Install system packages.

   ```bash
   sudo apt update
   sudo apt install -y \
     ros-humble-desktop \
     ros-humble-joy \
     python3-opencv \
     python3-pip \
     python3-serial \
     joystick \
     v4l-utils
   ```

2. Create and build the workspace.

   ```bash
   cd ~/MyDroid/ros2_ws
   pip3 install -r src/visual_following_car/requirements.txt
   source /opt/ros/humble/setup.bash
   colcon build --symlink-install
   source install/setup.bash
   ```

3. Pair the Bluetooth gamepad.

   ```bash
   bluetoothctl
   power on
   agent on
   default-agent
   scan on
   pair XX:XX:XX:XX:XX:XX
   trust XX:XX:XX:XX:XX:XX
   connect XX:XX:XX:XX:XX:XX
   exit
   ```

4. Verify the joystick.

   ```bash
   ls /dev/input/js*
   jstest /dev/input/js0
   ```

5. Add permission rules.

   ```bash
   sudo tee /etc/udev/rules.d/99-mydroid.rules >/dev/null <<'EOF'
   KERNEL=="js[0-9]*", MODE="0666", GROUP="plugdev"
   KERNEL=="ttyS1", MODE="0666", GROUP="dialout"
   EOF
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   sudo usermod -aG dialout,plugdev $USER
   ```

6. Launch the full robot.

   ```bash
   source /opt/ros/humble/setup.bash
   source ~/MyDroid/ros2_ws/install/setup.bash
   ros2 launch visual_following_car bringup.launch.py \
     serial_port:=/dev/ttyS1 \
     camera_device:=/dev/video0 \
     joy_dev:=/dev/input/js0
   ```

7. For manual-only testing, use:

   ```bash
   ros2 launch visual_following_car teleop_manual.launch.py
   ```

## STM32CubeIDE Setup

1. Create a new STM32CubeIDE project for `STM32F407VGTx`.
2. Generate a HAL project with `Main` and `GPIO` enabled.
3. Replace `Core/Src/main.c`, `Core/Src/stm32f4xx_it.c`, `Core/Inc/main.h`, and `Core/Inc/stm32f4xx_it.h` with the files in this repo.
4. Add `motor_control.c`, `protocol.c`, `app_config.h`, `motor_control.h`, and `protocol.h` into the project.
5. Configure clocks to match `SystemClock_Config()` in `main.c` or keep the provided code.
6. Enable the following peripherals and pins if you prefer to mirror CubeMX instead of using the source directly:
   - `USART1`: TX=`PA9`, RX=`PA10`, `115200 8N1`
   - `TIM3 PWM`: CH1=`PA6`, CH2=`PA7`, CH3=`PB0`, CH4=`PB1`
   - `TIM4 PWM`: CH1=`PB6`, CH2=`PB7`
   - GPIO outputs: `PC0-PC5`, `PB12`, `PB13`, `PB14`
7. Build and flash the board.
8. Confirm TTL UART level is `3.3V`, not RS232 level.

## Wiring

### ROCK 3B to STM32

- ROCK 3B UART TX -> STM32 `PA10` (`USART1_RX`)
- ROCK 3B UART RX -> STM32 `PA9` (`USART1_TX`)
- ROCK 3B GND -> STM32 GND

### STM32 to Motor Driver / Servos

- Front-left motor PWM: `PA6` (`TIM3_CH1`)
- Front-right motor PWM: `PA7` (`TIM3_CH2`)
- Rear-left motor PWM: `PB0` (`TIM3_CH3`)
- Rear-right motor PWM: `PB1` (`TIM3_CH4`)
- Front-left direction: `PC0`, `PC1`
- Front-right direction: `PC2`, `PC3`
- Rear-left direction: `PC4`, `PC5`
- Rear-right direction: `PB12`, `PB13`
- Driver standby: `PB14`
- Pan servo PWM: `PB6` (`TIM4_CH1`)
- Tilt servo PWM: `PB7` (`TIM4_CH2`)

### Power Notes

- Feed motor power from a dedicated motor supply.
- Feed servos from a stable `5V` rail sized for stall current.
- Tie all grounds together: ROCK 3B, STM32, motor driver, servo supply.
- Do not power the servos directly from the STM32 `5V` pin.

## Default Gamepad Mapping

These are the defaults in `config/visual_following_car.yaml` and can be changed there.

- Left stick vertical: forward/backward
- Left stick horizontal: strafe left/right
- Right stick horizontal: yaw
- D-pad horizontal: pan gimbal
- D-pad vertical: tilt gimbal
- `A` button: toggle manual / auto-follow
- `B` button: safety stop latch
- `X` button: re-center gimbal

### Controller Mapping Assistant (recommended for 雷神/other controllers)

If your controller (e.g., 雷神/Thunderobot) uses different axis/button indices, use the built-in mapping assistant to auto-detect and generate a YAML snippet to paste into `config/visual_following_car.yaml`.

1. Launch the teleop node (manual mode) normally, for example:

   ```bash
   ros2 launch visual_following_car teleop_manual.launch.py
   ```

2. Enable mapping assistant at runtime:

   ```bash
   ros2 param set /joy_teleop_node controller_model mapping_assistant
   ```

   The node will log step-by-step instructions. Follow the prompts:
   - Move the requested stick/control when prompted to map axes.
   - Press the requested button when prompted to map buttons.

3. After completion the node prints a YAML snippet. Paste that under `joy_teleop_node.ros__parameters` in `config/visual_following_car.yaml` and restart the node.

4. Alternatively, set `controller_model: mapping_assistant` in the YAML and restart to run detection on startup.

If you prefer manual mapping, you can also inspect raw Joystick messages:

```bash
# show raw joystick messages
ros2 topic echo /joy
# or on Linux use jstest
jstest /dev/input/js0
```

Then copy axis/button indices into the YAML keys `axes.*` and `buttons.*`.

## YOLOv8 Tips for RK3568

- Keep camera resolution at `640x480` or lower for CPU inference.
- Use `input_size: 320` or `416` if CPU load is high.
- Start with `inference_rate_hz: 8-10`.
- Use `yolov8n.pt` first; upgrade only if accuracy is insufficient.
- Download weights once before runtime to avoid first-run delay:

  ```bash
  python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
  ```

- If later you move to RKNN or ONNX Runtime, keep the ROS interfaces unchanged and replace only the detector internals.

## Calibration

### Gimbal Neutral and Direction

1. Run manual mode with the camera pointing straight ahead.
2. Press the gimbal re-center button.
3. If the camera is not centered mechanically, adjust:
   - ROS YAML: `pan_neutral_deg`, `tilt_neutral_deg`
   - STM32 `app_config.h`: `PAN_SERVO_NEUTRAL_DEG`, `TILT_SERVO_NEUTRAL_DEG`
4. If pan or tilt moves in the wrong direction, flip:
   - ROS YAML: `pan_axis_sign`, `tilt_axis_sign`
   - STM32 `PAN_SERVO_REVERSED`, `TILT_SERVO_REVERSED`

### Mecanum Direction and Speed

1. Start in `teleop_manual.launch.py`.
2. Push forward and verify all wheels drive the robot forward.
3. If any wheel direction is wrong, flip one of:
   - Motor wiring on the driver
   - `FRONT_LEFT_MOTOR_REVERSED`, `FRONT_RIGHT_MOTOR_REVERSED`, `REAR_LEFT_MOTOR_REVERSED`, `REAR_RIGHT_MOTOR_REVERSED`
4. Tune `MAX_WHEEL_ANGULAR_SPEED_RADPS` until PWM scaling matches your chassis.
5. Tune ROS gains in `visual_following_car.yaml`:
   - `distance_kp`
   - `strafe_kp`
   - `omega_from_pan_kp`
   - `pan_pid.*`
   - `tilt_pid.*`

### Distance Estimate

Distance is estimated from person height and bounding-box height.

Use this formula to calibrate `camera_focal_length_px`:

```text
camera_focal_length_px = (bbox_height_px * real_target_height_m) / measured_distance_m
```

Measure a person at a known distance, record the box height in pixels, then update `camera_focal_length_px` in the YAML.
