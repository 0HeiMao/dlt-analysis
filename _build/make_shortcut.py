"""在桌面创建「超级大乐透历史数据分析工具」快捷方式。

目标：pythonw.exe launch_tool.py（无黑窗），服务以脱离控制台的后台进程运行，
关掉浏览器或终端都不会带走它；重复启动不会重复拉起（幂等）。
停止请用桌面的「停止大乐透分析工具」快捷方式（stop_tool.py）。
"""

import os
import sys

from pylnk3 import for_file

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(PROJ, "assets")
os.makedirs(ASSETS, exist_ok=True)


def find_pythonw() -> str:
    """优先用当前解释器同目录的 pythonw.exe（无黑窗），找不到就退回 python.exe。"""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def find_desktop() -> str:
    """定位桌面目录，兼容 OneDrive 接管桌面的情况。"""
    home = os.path.expanduser("~")
    for p in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(p):
            return p
    return os.path.join(home, "Desktop")


PYTHONW = find_pythonw()
LAUNCHER = os.path.join(PROJ, "launch_tool.py")
# 图标放项目内 assets/：此前放桌面，桌面文件被清理后图标就失效了
ICON = os.path.join(ASSETS, "lucky-star-five.ico")
DESKTOP = find_desktop()
LNK = os.path.join(DESKTOP, "超级大乐透历史数据分析工具.lnk")
WORK_DIR = PROJ
DESC = "启动本地大乐透历史数据分析工具 (http://127.0.0.1:8765)"

for path in (PYTHONW, LAUNCHER, ICON):
    if not os.path.exists(path):
        print("missing:", path)
        sys.exit(1)

for_file(
    PYTHONW,
    LNK,
    arguments=f'"{LAUNCHER}"',
    description=DESC,
    icon_file=ICON,
    icon_index=0,
    work_dir=WORK_DIR,
    window_mode="Minimized",
)

raw = open(LNK, "rb").read()
checks = {
    "目标 pythonw.exe": "pythonw.exe".encode("utf-16-le") in raw,
    "参数 launch_tool.py": "launch_tool.py".encode("utf-16-le") in raw,
    "图标 lucky-star-five.ico": "lucky-star-five.ico".encode("utf-16-le") in raw,
    "工作目录 dlt_analysis": "dlt_analysis".encode("utf-16-le") in raw,
}
print("lnk:", LNK)
print("size:", len(raw), "bytes")
for k, v in checks.items():
    print(f"  {k}: {v}")
