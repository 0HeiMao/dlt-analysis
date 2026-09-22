"""启动本地大乐透分析工具：后台拉起 FastAPI 服务并打开浏览器。

用法：
    pythonw launch_tool.py                # 桌面快捷方式使用的方式：无窗口
    python  launch_tool.py                # 等价
    python  launch_tool.py --no-browser   # 只起服务不开浏览器（自动化测试用）
    python  launch_tool.py --foreground   # 弹出控制台窗口（调试用，关窗即停）

服务以脱离控制台的后台进程运行，日志写入 _build/server.log，
关掉浏览器或本脚本都不会把它带走；停止请用 stop_tool.py（桌面有对应快捷方式）。
服务已运行时不会重复拉起，直接打开页面。

不再依赖 netstat / taskkill 等外部命令，改用 portutil 的 ctypes 实现。
"""

import os
import socket
import subprocess
import sys
import time
import webbrowser

from portutil import listener_pids, port_open, kill_pids

PORT = 8765
HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.join(HERE, "webapp")
BUILD = os.path.join(HERE, "_build")
LOG = os.path.join(BUILD, "launch_error.log")
SERVER_LOG = os.path.join(BUILD, "server.log")
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
# 主动脱离父进程的 job 对象。若本进程本身不在 job 内（真实桌面 .lnk → pythonw.exe
# 场景），此标志被忽略、无副作用；若处于带 JOB_OBJECT_LIMIT_BREAKAWAY_OK 的 job 内
# （如命令执行沙箱），子进程借此脱离 job，避免命令结束时整树回收，服务得以跨命令存活。
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def _tail(path: str, n: int = 40) -> list:
    """读取日志文件末尾 n 行（用于启动失败时附上诊断信息）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
        return lines[-n:]
    except Exception:
        return []


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    no_browser = "--no-browser" in argv
    foreground = "--foreground" in argv

    # (a) 僵尸端口处理：端口被占（有进程 LISTEN 该端口）但连不上，说明是
    # 僵尸/半死进程，先杀掉再走启动流程，避免 Address already in use。
    pids = listener_pids(PORT)
    if pids and not port_open(PORT):
        kill_pids(pids)
        time.sleep(0.5)

    if not port_open(PORT):
        os.makedirs(BUILD, exist_ok=True)
        if foreground:
            subprocess.Popen(
                [sys.executable, "server.py"],
                cwd=WEBAPP,
                creationflags=CREATE_NEW_CONSOLE,
            )
        else:
            log = open(SERVER_LOG, "a", encoding="utf-8")
            subprocess.Popen(
                [sys.executable, "server.py"],
                cwd=WEBAPP,
                creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
            )
        for _ in range(60):
            time.sleep(0.5)
            if port_open(PORT):
                break

    if not port_open(PORT):
        # (b) 启动失败诊断：除了现有 launch_error.log，把 server.log 末尾 40 行也附上，
        # 常见失败原因是 Address already in use，不看日志根本定位不到。
        # (c) 不要误报成功：无论是否 --no-browser，超时都必须返回 1。
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "w", encoding="utf-8") as f:
            f.write(f"服务未能在 30 秒内监听 127.0.0.1:{PORT}\n")
            f.write(f"请手动检查：cd {WEBAPP} && python server.py\n\n")
            f.write("===== server.log 末尾 40 行 =====\n")
            tail_lines = _tail(SERVER_LOG, 40)
            f.write("\n".join(tail_lines) + "\n")
        if not no_browser:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return 1

    if not no_browser:
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
