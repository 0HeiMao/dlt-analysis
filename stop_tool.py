"""停止本地大乐透分析工具：按端口找出服务进程并终止。

用法：
    pythonw stop_tool.py     # 桌面「停止」快捷方式使用（无窗口，print 看不见，失败落盘）
    python  stop_tool.py     # 等价，可在控制台看到结果

不再依赖 netstat / taskkill 等外部命令（Git Bash 环境下 PATH 是 POSIX 风格，
Windows 不识别，会导致 netstat 找不到而误报「端口无监听」）。改用 portutil
里的 ctypes 实现，纯标准库、零外部依赖。
"""

import os
import sys
import time

from portutil import listener_pids, port_open, kill_pids

PORT = 8765
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "_build")
STOP_ERROR_LOG = os.path.join(BUILD, "stop_error.log")


def main() -> int:
    pids = listener_pids(PORT)
    if not pids:
        print(f"端口 {PORT} 无监听，服务未在运行")
        return 0

    kill_pids(pids)

    for _ in range(30):
        time.sleep(0.3)
        if not port_open(PORT):
            print(f"已停止服务，端口 {PORT} 已释放（终止 PID: {', '.join(str(p) for p in pids)}）")
            return 0

    # 30 次轮询后端口仍被占用：pythonw 模式下 print 用户看不见，必须把失败落盘。
    msg = f"已发送终止指令，但端口 {PORT} 仍在监听（PID: {', '.join(str(p) for p in pids)}）"
    print(msg)
    try:
        os.makedirs(BUILD, exist_ok=True)
        with open(STOP_ERROR_LOG, "w", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
