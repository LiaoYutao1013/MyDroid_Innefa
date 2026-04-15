#!/usr/bin/env python3
"""
简单 UART 发送工具 - 向 Radxa ROCK 3B 发送数据

用于控制主板发送信息给 STM32。

使用方法：
    python3 tools/simple_send_tool.py --port COM11 --baud 115200 --message "Hello STM32"
"""

import argparse
import sys
import time

try:
    import serial
except ImportError:
    print("请先安装 pyserial: pip install pyserial")
    sys.exit(1)


def send_message(port: str, baud: int, message: str, hex_mode: bool = False):
    """发送消息到指定串口"""
    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"✓ 连接到 {port} @ {baud} baud")

        if hex_mode:
            # 解析十六进制字符串，如 "AA 55 01"
            try:
                data = bytes.fromhex(message.replace(' ', ''))
            except ValueError as e:
                print(f"✗ 十六进制格式错误: {e}")
                return False
        else:
            data = message.encode('utf-8')

        print(f"发送数据: {data.hex(' ')} (ASCII: {message})")
        ser.write(data)
        ser.flush()

        print("✓ 发送完成")
        ser.close()
        return True

    except Exception as e:
        print(f"✗ 发送失败: {e}")
        return False


def interactive_mode(port: str, baud: int):
    """交互模式"""
    print(f"进入交互模式，连接到 {port} @ {baud}")
    print("输入 'quit' 退出，'help' 查看帮助")

    while True:
        try:
            cmd = input("> ").strip()
            if not cmd:
                continue

            if cmd.lower() in ('q', 'quit', 'exit'):
                break
            elif cmd.lower() == 'help':
                print("命令:")
                print("  <text>          发送文本")
                print("  hex <bytes>     发送十六进制，如 hex AA 55 01")
                print("  quit            退出")
            elif cmd.startswith('hex '):
                hex_str = cmd[4:].strip()
                send_message(port, baud, hex_str, hex_mode=True)
            else:
                send_message(port, baud, cmd, hex_mode=False)

        except KeyboardInterrupt:
            print("\n退出")
            break
        except Exception as e:
            print(f"错误: {e}")


def main():
    parser = argparse.ArgumentParser(description='简单 UART 发送工具')
    parser.add_argument('--port', required=True, help='串口名称，如 COM11 或 /dev/ttyUSB0')
    parser.add_argument('--baud', type=int, default=115200, help='波特率，默认 115200')
    parser.add_argument('--message', help='要发送的消息（文本）')
    parser.add_argument('--hex', help='要发送的十六进制数据，如 "AA 55 01"')
    parser.add_argument('--interactive', action='store_true', help='进入交互模式')

    args = parser.parse_args()

    if args.interactive:
        interactive_mode(args.port, args.baud)
    elif args.message:
        send_message(args.port, args.baud, args.message, hex_mode=False)
    elif args.hex:
        send_message(args.port, args.baud, args.hex, hex_mode=True)
    else:
        print("请指定 --message 或 --hex 或 --interactive")
        parser.print_help()


if __name__ == '__main__':
    main()