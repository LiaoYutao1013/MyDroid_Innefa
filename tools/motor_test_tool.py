#!/usr/bin/env python3
"""
Motor Test Tool for Radxa ROCK 3B
独立电机驱动测试工具 - 通过UART与STM32通信

使用方法：
    python3 motor_test_tool.py [--port /dev/ttyUSB0] [--baud 115200]

命令：
    M <id> <duty>      - 设置电机速度 (id:0-3, duty:-1000~1000)
    E <id>              - 读取编码器
    S                   - 停止所有电机
    X                   - 紧急停止
    T [duration]        - 自动测试 (默认5秒)
    A [duration]        - 加速度测试
    Q                   - 退出
"""

import serial
import time
import sys
import argparse
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List
import csv

@dataclass
class MotorReading:
    """单次电机数据采样"""
    timestamp: float
    motor_id: int
    pwm_duty: int
    encoder_count: int
    encoder_rpm: int

class MotorTestTool:
    def __init__(self, port: str = '/dev/ttyUSB0', baud: int = 115200):
        """初始化串口连接"""
        self.port = port
        self.baud = baud
        self.ser = None
        self.connection_ok = False
        self.readings: List[MotorReading] = []
        self.running = True

        self._connect()

    def _connect(self):
        """建立串口连接"""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            time.sleep(1)  # 等待STM32复位
            self.connection_ok = True
            print(f"✓ Connected to {self.port} @ {self.baud} baud")
        except Exception as e:
            print(f"✗ Failed to connect: {e}")
            self.connection_ok = False
            sys.exit(1)

    def send_command(self, cmd: str) -> Optional[str]:
        """发送命令并接收响应"""
        if not self.connection_ok:
            print("Error: Serial connection not established")
            return None

        try:
            # 清空接收缓冲
            self.ser.reset_input_buffer()

            # 发送命令
            self.ser.write((cmd + '\n').encode())

            # 读取响应（单行）
            response = self.ser.readline().decode().strip()
            return response
        except Exception as e:
            print(f"Comm error: {e}")
            return None

    def set_motor(self, motor_id: int, duty: int):
        """设置单电机速度"""
        if not (0 <= motor_id < 4):
            print(f"Error: Invalid motor_id {motor_id}, must be 0-3")
            return False

        if not (-1000 <= duty <= 1000):
            print(f"Error: Invalid duty {duty}, must be -1000~1000")
            return False

        cmd = f"M {motor_id} {duty}"
        resp = self.send_command(cmd)

        if resp and "OK" in resp:
            print(f"Motor {motor_id}: {duty/10:.1f}%")
            return True
        else:
            print(f"Failed to set motor {motor_id}")
            return False

    def set_all_motors(self, fl: int, fr: int, rl: int, rr: int):
        """同时设置4个电机"""
        for idx, duty in enumerate([fl, fr, rl, rr]):
            self.set_motor(idx, duty)

    def stop_all(self):
        """停止所有电机"""
        resp = self.send_command("S")
        print("All motors stopped")

    def emergency_stop(self):
        """紧急停止"""
        resp = self.send_command("X")
        print("⚠ EMERGENCY STOP")

    def get_encoder(self, motor_id: int) -> Optional[tuple]:
        """读取编码器值
        返回: (encoder_count, rpm)
        """
        if not (0 <= motor_id < 4):
            return None

        resp = self.send_command(f"E {motor_id}")
        if resp:
            try:
                # 解析: "E <id>: count=<count> rpm=<rpm>"
                parts = resp.split()
                count = int(parts[1].split('=')[1])
                rpm = int(parts[2].split('=')[1])
                return count, rpm
            except:
                print(f"Failed to parse encoder response: {resp}")
                return None
        return None

    def read_all_encoders(self) -> List[MotorReading]:
        """读取所有4个电机的编码器"""
        readings = []
        timestamp = time.time()

        for motor_id in range(4):
            result = self.get_encoder(motor_id)
            if result:
                count, rpm = result
                reading = MotorReading(
                    timestamp=timestamp,
                    motor_id=motor_id,
                    pwm_duty=0,  # 需要额外查询
                    encoder_count=count,
                    encoder_rpm=rpm
                )
                readings.append(reading)

        return readings

    def test_single_motor(self, motor_id: int, duration_sec: int = 3,
                         max_duty: int = 500):
        """测试单个电机"""
        print(f"\n=== Testing Motor {motor_id} ({duration_sec}s) ===")

        # 启动电机
        self.set_motor(motor_id, max_duty)

        # 采样
        start_time = time.time()
        samples = []

        while time.time() - start_time < duration_sec:
            result = self.get_encoder(motor_id)
            if result:
                count, rpm = result
                elapsed = time.time() - start_time
                samples.append((elapsed, count, rpm))
                print(f"  {elapsed:.1f}s: count={count:6d}, rpm={rpm:4d}")
            time.sleep(0.5)

        # 停止电机
        self.set_motor(motor_id, 0)

        # 分析数据
        if len(samples) > 1:
            total_displacement = samples[-1][1] - samples[0][1]
            avg_rpm = sum(s[2] for s in samples) / len(samples)
            print(f"Result: Displacement={total_displacement} pulses, Avg RPM={avg_rpm:.1f}")

        return samples

    def test_all_motors_sync(self, duration_sec: int = 3, duty: int = 500):
        """测试四电机同步性"""
        print(f"\n=== Testing All Motors Synchronization ({duration_sec}s) ===")

        # 启动所有电机
        self.set_all_motors(duty, duty, duty, duty)

        # 采样
        start_time = time.time()
        samples = {i: [] for i in range(4)}

        while time.time() - start_time < duration_sec:
            readings = self.read_all_encoders()
            elapsed = time.time() - start_time

            for reading in readings:
                samples[reading.motor_id].append((elapsed, reading.encoder_count, reading.encoder_rpm))

            # 打印实时数据
            line = f"  {elapsed:.1f}s: "
            for motor_id in range(4):
                if samples[motor_id]:
                    _, count, rpm = samples[motor_id][-1]
                    line += f"M{motor_id}={rpm:4d}rpm "
            print(line)

            time.sleep(0.5)

        # 停止电机
        self.stop_all()

        # 分析同步性
        print("\nSynchronization Analysis:")
        rpms = []
        for motor_id in range(4):
            if samples[motor_id]:
                avg_rpm = sum(s[2] for s in samples[motor_id]) / len(samples[motor_id])
                rpms.append(avg_rpm)
                print(f"  Motor {motor_id}: Avg RPM = {avg_rpm:.1f}")

        if rpms:
            avg = sum(rpms) / len(rpms)
            max_deviation = max(abs(rpm - avg) for rpm in rpms)
            consistency = 100 * (1 - max_deviation / avg) if avg > 0 else 0
            print(f"  Overall Consistency: {consistency:.1f}%")

    def acceleration_test(self, motor_id: int, duration_sec: int = 5):
        """加速度测试：逐步增加PWM，观察响应"""
        print(f"\n=== Acceleration Test Motor {motor_id} ({duration_sec}s) ===")

        steps = 5
        step_duration = duration_sec / steps
        pwm_values = [i * 200 for i in range(1, steps + 1)]  # 200, 400, 600, 800, 1000

        for pwm in pwm_values:
            print(f"\nSet PWM to {pwm/10:.0f}%:")
            self.set_motor(motor_id, pwm)

            # 采样该PWM水平下的数据
            for _ in range(3):  # 采3个样本
                result = self.get_encoder(motor_id)
                if result:
                    count, rpm = result
                    print(f"  count={count:6d}, rpm={rpm:4d}")
                time.sleep(step_duration / 3)

        self.stop_all()

    def interactive_mode(self):
        """交互式命令行模式"""
        print("\n=== Motor Test Interactive Mode ===")
        print("Type 'H' for help, 'Q' to quit\n")

        while self.running:
            try:
                user_input = input("> ").strip()

                if not user_input:
                    continue

                tokens = user_input.upper().split()
                cmd = tokens[0] if tokens else ''

                if cmd == 'Q':
                    self.stop_all()
                    self.running = False
                    print("Goodbye!")
                    break

                elif cmd == 'H':
                    print(self.__class__.__doc__)

                elif cmd == 'M' and len(tokens) >= 3:
                    motor_id = int(tokens[1])
                    duty = int(tokens[2])
                    self.set_motor(motor_id, duty)

                elif cmd == 'E' and len(tokens) >= 2:
                    motor_id = int(tokens[1])
                    result = self.get_encoder(motor_id)
                    if result:
                        count, rpm = result
                        print(f"Motor {motor_id}: count={count}, rpm={rpm}")

                elif cmd == 'S':
                    self.stop_all()

                elif cmd == 'X':
                    self.emergency_stop()

                elif cmd == 'T':
                    duration = int(tokens[1]) if len(tokens) > 1 else 5
                    # 检测是否指定了特定电机
                    motor_id = int(tokens[2]) if len(tokens) > 2 else None

                    if motor_id is not None:
                        self.test_single_motor(motor_id, duration)
                    else:
                        self.test_all_motors_sync(duration)

                elif cmd == 'A':
                    motor_id = int(tokens[1]) if len(tokens) > 1 else 0
                    self.acceleration_test(motor_id)

                elif cmd == 'C':
                    self.send_command(user_input)

                else:
                    print(f"Unknown command: {user_input}")
                    print("Type 'H' for help")

            except KeyboardInterrupt:
                print("\nInterrupted!")
                self.stop_all()
                self.running = False
            except Exception as e:
                print(f"Error: {e}")

    def save_data_csv(self, filename: str = "motor_test_data.csv"):
        """保存测试数据到CSV"""
        if not self.readings:
            print("No data to save")
            return

        try:
            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'motor_id', 'pwm_duty', 'encoder_count', 'encoder_rpm'])
                for reading in self.readings:
                    writer.writerow([
                        reading.timestamp,
                        reading.motor_id,
                        reading.pwm_duty,
                        reading.encoder_count,
                        reading.encoder_rpm
                    ])
            print(f"Data saved to {filename}")
        except Exception as e:
            print(f"Failed to save data: {e}")

def main():
    parser = argparse.ArgumentParser(description="Motor Test Tool for MyDroid")
    parser.add_argument('--port', default='/dev/ttyUSB0',
                       help='Serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--baud', type=int, default=115200,
                       help='Baud rate (default: 115200)')
    parser.add_argument('--test', action='store_true',
                       help='Run automated tests and exit')

    args = parser.parse_args()

    tool = MotorTestTool(args.port, args.baud)

    if args.test:
        # 自动测试模式
        print("\n=== Automated Test Sequence ===\n")

        print("1. Testing individual motors...")
        for motor_id in range(4):
            tool.test_single_motor(motor_id, duration_sec=2, max_duty=300)
            time.sleep(1)

        print("\n2. Testing synchronization...")
        tool.test_all_motors_sync(duration_sec=3, duty=400)

        print("\n3. Testing acceleration response...")
        tool.acceleration_test(motor_id=0, duration_sec=3)

        print("\n=== Test Completed ===\n")
    else:
        # 交互式模式
        tool.interactive_mode()

    if tool.ser:
        tool.ser.close()

if __name__ == '__main__':
    main()
