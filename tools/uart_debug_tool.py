#!/usr/bin/env python3
"""
UART Debug Tool for Radxa ROCK 3B <-> STM32

本脚本用于调试 Radxa ROCK 3B 与 STM32 的串口通信。
它可以同时打开两路串口，打印收发数据，支持交互发送和可选转发模式。

示例：
    python3 tools/uart_debug_tool.py --rock-port COM5 --stm-port COM6 --baud 115200
"""

import argparse
import queue
import sys
import threading
import time

try:
    import serial
except ImportError:
    print("请先安装 pyserial: pip install pyserial")
    sys.exit(1)


def format_bytes(data: bytes) -> str:
    if not data:
        return ""
    try:
        text = data.decode('utf-8', errors='replace')
    except Exception:
        text = '<decode-error>'
    hexstr = ' '.join(f'{b:02X}' for b in data)
    return f"ASCII: {text} | HEX: {hexstr}"


class SerialEndpoint(threading.Thread):
    def __init__(self, name: str, ser: serial.Serial, output_queue: queue.Queue):
        super().__init__(daemon=True)
        self.name = name
        self.ser = ser
        self.output_queue = output_queue
        self.running = True

    def run(self):
        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    self.output_queue.put((self.name, data))
                else:
                    time.sleep(0.01)
            except Exception as exc:
                self.output_queue.put((self.name, f"<read-error: {exc}>".encode()))
                self.running = False

    def stop(self):
        self.running = False


class UartDebugTool:
    def __init__(self, rock_port: str, stm_port: str, baud: int, timeout: float):
        self.rock_port = rock_port
        self.stm_port = stm_port
        self.baud = baud
        self.timeout = timeout
        self.rock_ser = None
        self.stm_ser = None
        self.output_queue = queue.Queue()
        self.command_queue = queue.Queue()
        self.rock_thread = None
        self.stm_thread = None
        self.command_thread = None
        self.bridge_enabled = False

    def open_ports(self):
        print(f"打开 Radxa 串口: {self.rock_port} @ {self.baud}")
        self.rock_ser = serial.Serial(self.rock_port, self.baud, timeout=self.timeout)
        print(f"打开 STM32 串口: {self.stm_port} @ {self.baud}")
        self.stm_ser = serial.Serial(self.stm_port, self.baud, timeout=self.timeout)

        self.rock_thread = SerialEndpoint('ROCK', self.rock_ser, self.output_queue)
        self.stm_thread = SerialEndpoint('STM', self.stm_ser, self.output_queue)
        self.rock_thread.start()
        self.stm_thread.start()

    def close_ports(self):
        print("正在关闭串口...")
        if self.rock_thread:
            self.rock_thread.stop()
        if self.stm_thread:
            self.stm_thread.stop()
        time.sleep(0.1)
        if self.rock_ser and self.rock_ser.is_open:
            self.rock_ser.close()
        if self.stm_ser and self.stm_ser.is_open:
            self.stm_ser.close()

    def send_to_port(self, port_name: str, payload: bytes):
        if port_name == 'rock':
            ser = self.rock_ser
        elif port_name == 'stm':
            ser = self.stm_ser
        else:
            print(f"未知端口: {port_name}")
            return

        if not ser or not ser.is_open:
            print(f"端口 {port_name} 未打开")
            return

        ser.write(payload)
        ser.flush()
        print(f"[SEND {port_name.upper()}] {format_bytes(payload)}")

    def bridge_data(self, source: str, data: bytes):
        if not self.bridge_enabled:
            return
        target = 'stm' if source == 'ROCK' else 'rock'
        self.send_to_port(target, data)

    def run(self):
        try:
            self.open_ports()
            self.start_command_thread()
            print("串口已打开，输入 help 查看命令。按 Ctrl+C 退出。\n")
            self.print_help()

            while True:
                while not self.output_queue.empty():
                    name, payload = self.output_queue.get()
                    if isinstance(payload, bytes):
                        print(f"[{name}] {format_bytes(payload)}")
                        self.bridge_data(name, payload)
                    else:
                        print(f"[{name}] {payload}")

                while not self.command_queue.empty():
                    line = self.command_queue.get()
                    self.handle_command(line)

                time.sleep(0.05)
        except KeyboardInterrupt:
            print("\n用户终止")
        finally:
            self.close_ports()

    def start_command_thread(self):
        self.command_thread = threading.Thread(target=self.input_loop, daemon=True)
        self.command_thread.start()

    def input_loop(self):
        try:
            while True:
                line = sys.stdin.readline()
                if not line:
                    break
                self.command_queue.put(line.strip())
        except Exception:
            pass

    def handle_command(self, raw: str):
        if not raw:
            return
        args = raw.split()
        cmd = args[0].lower()

        if cmd in ('q', 'quit', 'exit'):
            raise KeyboardInterrupt()
        elif cmd in ('h', 'help'):
            self.print_help()
        elif cmd == 'bridge':
            if len(args) >= 2 and args[1].lower() in ('on', 'off'):
                self.bridge_enabled = args[1].lower() == 'on'
                print(f"桥接模式 {'已启用' if self.bridge_enabled else '已禁用'}")
            else:
                print("用法: bridge on | bridge off")
        elif cmd in ('rock', 'stm'):
            if len(args) >= 2:
                mode = 'hex' if args[1].lower() == 'hex' else 'text'
                if mode == 'hex':
                    data = parse_hex_bytes(args[2:])
                else:
                    data = ' '.join(args[1:]).encode('utf-8')
                self.send_to_port(cmd, data)
            else:
                print(f"用法: {cmd} <text> 或 {cmd} hex <0xAA 0xBB> ...")
        elif cmd == 'send':
            if len(args) >= 3 and args[1].lower() in ('rock', 'stm'):
                target = args[1].lower()
                if args[2].lower() == 'hex':
                    data = parse_hex_bytes(args[3:])
                else:
                    data = ' '.join(args[2:]).encode('utf-8')
                self.send_to_port(target, data)
            else:
                print("用法: send rock|stm <text> 或 send rock|stm hex <bytes>")
        else:
            print(f"未知命令: {cmd}. 输入 help 查看可用命令。")

    def print_help(self):
        print("可用命令:")
        print("  help                    显示本帮助")
        print("  quit / q / exit         退出程序")
        print("  bridge on|off           开启/关闭自动转发模式")
        print("  rock <text>             向 Radxa 端发送文本")
        print("  stm <text>              向 STM32 端发送文本")
        print("  rock hex <bytes>        向 Radxa 端发送十六进制字节")
        print("  stm hex <bytes>         向 STM32 端发送十六进制字节")
        print("  send rock|stm <text>    发送数据到指定端口")
        print("  send rock|stm hex ...   发送十六进制字节")
        print("  示例: rock STATUS")
        print("  示例: stm hex 0xAA 0x55 0x01")


def parse_hex_bytes(tokens):
    out = bytearray()
    for token in tokens:
        token = token.strip()
        if token.startswith('0x') or token.startswith('0X'):
            token = token[2:]
        if len(token) == 0:
            continue
        try:
            out.append(int(token, 16))
        except ValueError:
            print(f"无法解析十六进制: {token}")
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description='Radxa ROCK3B <-> STM32 UART 调试工具')
    parser.add_argument('--rock-port', required=True, help='Radxa 串口名称，例如 COM5 或 /dev/ttyUSB0')
    parser.add_argument('--stm-port', required=True, help='STM32 串口名称，例如 COM6 或 /dev/ttyUSB1')
    parser.add_argument('--baud', type=int, default=115200, help='波特率，默认 115200')
    parser.add_argument('--timeout', type=float, default=0.2, help='串口读超时（秒），默认 0.2')

    args = parser.parse_args()
    tool = UartDebugTool(args.rock_port, args.stm_port, args.baud, args.timeout)
    try:
        tool.run()
    except KeyboardInterrupt:
        pass
    finally:
        tool.close_ports()


if __name__ == '__main__':
    main()
