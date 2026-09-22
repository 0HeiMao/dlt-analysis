"""登录后自动拉起本地大乐透分析服务。

做法：在 Windows「启动」文件夹放一个快捷方式，指向 pythonw launch_tool.py --no-browser。
- 登录后服务即在后台跑起来（无黑窗、不弹浏览器），http://127.0.0.1:8765 直接可用。
- launch_tool.py 本身幂等：服务已在运行就跳过，不会重复拉起、不会端口冲突。

不想再自启，删掉这个快捷方式即可：
    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\大乐透分析工具自启动.lnk
"""

import os
import sys

from pylnk3 import for_file

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(PROJ, "assets")
LAUNCHER = os.path.join(PROJ, "launch_tool.py")
ICON = os.path.join(ASSETS, "lucky-star-five.ico")


def find_pythonw() -> str:
    """优先用当前解释器同目录的 pythonw.exe（无黑窗），找不到就退回 python.exe。"""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


PYTHONW = find_pythonw()

APPDATA = os.environ.get("APPDATA", "")
STARTUP = os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup")
LNK = os.path.join(STARTUP, "大乐透分析工具自启动.lnk")


def main() -> int:
    for path in (PYTHONW, LAUNCHER, ICON):
        if not os.path.exists(path):
            print("missing:", path)
            return 1
    if not os.path.isdir(STARTUP):
        print("missing startup dir:", STARTUP)
        return 1

    for_file(
        PYTHONW,
        LNK,
        arguments=f'"{LAUNCHER}" --no-browser',
        description="登录后自动启动本地大乐透分析服务 (127.0.0.1:8765)",
        icon_file=ICON,
        icon_index=0,
        work_dir=PROJ,
        window_mode="Minimized",
    )

    raw = open(LNK, "rb").read()
    checks = {
        "目标 pythonw.exe": "pythonw.exe".encode("utf-16-le") in raw,
        "参数 launch_tool.py": "launch_tool.py".encode("utf-16-le") in raw,
        "参数 --no-browser": "--no-browser".encode("utf-16-le") in raw,
        "图标 lucky-star-five.ico": "lucky-star-five.ico".encode("utf-16-le") in raw,
    }
    print("autostart lnk:", LNK)
    print("size:", len(raw), "bytes")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print("取消自启：删除上面的 .lnk 即可")
    return 0


if __name__ == "__main__":
    sys.exit(main())
