"""生成「停止」图标 ICO 与桌面停止快捷方式。

图标语义：琥珀圆角底 + 白色方块（停止符号），与启动用的幸运星形成配对。
"""

import os
import sys

from PIL import Image, ImageDraw
from pylnk3 import for_file

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT = os.path.dirname(_HERE)
ASSETS = os.path.join(_PROJECT, "assets")
os.makedirs(ASSETS, exist_ok=True)
# 图标落在项目内 assets/，不依赖桌面文件（桌面文件易被清理，丢失后图标会失效）
ICON = os.path.join(ASSETS, "lucky-star-stop.ico")


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


DESKTOP = find_desktop()
LNK = os.path.join(DESKTOP, "停止大乐透分析工具.lnk")
PYTHONW = find_pythonw()
STOPPER = os.path.join(_PROJECT, "stop_tool.py")
WORK_DIR = _PROJECT

BG = (186, 117, 23, 255)      # #BA7517
FG = (255, 255, 255, 255)
SIZES = [256, 128, 64, 48, 32, 16]
SS = 4


def render(size: int) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = big * 0.22
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius, fill=BG)
    inner = big * 0.30
    d.rounded_rectangle(
        [inner, inner, big - inner - 1, big - inner - 1],
        radius=big * 0.05,
        fill=FG,
    )
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    render(256).save(ICON, format="ICO", sizes=[(s, s) for s in SIZES])
    print("icon:", ICON, os.path.getsize(ICON), "bytes")

    for path in (PYTHONW, STOPPER):
        if not os.path.exists(path):
            print("missing:", path)
            return 1

    for_file(
        PYTHONW,
        LNK,
        arguments=f'"{STOPPER}"',
        description="停止本地大乐透分析工具服务 (释放 127.0.0.1:8765)",
        icon_file=ICON,
        icon_index=0,
        work_dir=WORK_DIR,
        window_mode="Minimized",
    )
    raw = open(LNK, "rb").read()
    checks = {
        "目标 pythonw.exe": "pythonw.exe".encode("utf-16-le") in raw,
        "参数 stop_tool.py": "stop_tool.py".encode("utf-16-le") in raw,
        "图标 lucky-star-stop.ico": "lucky-star-stop.ico".encode("utf-16-le") in raw,
    }
    print("lnk:", LNK, len(raw), "bytes")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
