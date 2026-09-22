"""把 lucky-star-five.svg 的几何渲染成多尺寸 Windows ICO。

几何与 SVG 保持一致（128x128 设计栅格）：
- 五角星：外半径 52、内半径 21.6，中心 (64,64)
- 两颗四角碎星：中心 (104,40) r=10、中心 (30,95) r=7
渲染用 4 倍超采样后 LANCZOS 缩回，避免锯齿；小于 32px 时省略碎星。
"""

from PIL import Image, ImageDraw

# 图标落在项目内的 assets/ 目录，而不是桌面：桌面文件容易被清理，
# 一旦丢失所有快捷方式都会退回默认图标（此前就是这样失效的）。
import os as _os
_ASSETS = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "assets")
_os.makedirs(_ASSETS, exist_ok=True)
OUT = _os.path.join(_ASSETS, "lucky-star-five.ico")
SIZES = [256, 128, 64, 48, 32, 16]
SS = 4

FILL = (250, 199, 117, 255)      # #FAC775
STROKE = (186, 117, 23, 255)     # #BA7517
SPARK = (239, 159, 39, 255)      # #EF9F27

STAR = [
    (64, 12), (76.7, 46.5), (113.5, 47.9), (84.5, 70.7), (94.6, 106.1),
    (64, 85.6), (33.4, 106.1), (43.5, 70.7), (14.5, 47.9), (51.3, 46.5),
]


def sparkle(cx, cy, r):
    w = r * 0.22
    return [
        (cx, cy - r), (cx + w, cy - w), (cx + r, cy), (cx + w, cy + w),
        (cx, cy + r), (cx - w, cy + w), (cx - r, cy), (cx - w, cy - w),
    ]


def scale(points, k):
    return [(x * k, y * k) for x, y in points]


def render(size):
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = big / 128.0
    if size <= 16:
        # 16px：描边会吃掉星角，改用深一档实心填充保住剪影（浅底上也看得清）
        d.polygon(scale(STAR, k), fill=SPARK)
    elif size <= 32:
        # 32px：1px 描边仍可用，维持双色
        width = max(1, round(size * 3 / 128.0 * SS))
        d.polygon(scale(STAR, k), fill=FILL, outline=STROKE, width=width)
    else:
        width = max(1, round(size * 3 / 128.0 * SS))
        d.polygon(scale(STAR, k), fill=FILL, outline=STROKE, width=width)
        d.polygon(scale(sparkle(104, 40, 10), k), fill=SPARK)
        d.polygon(scale(sparkle(30, 95, 7), k), fill=SPARK)
    return img.resize((size, size), Image.LANCZOS)


def main():
    base = render(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    check = Image.open(OUT)
    print("saved:", OUT)
    print("ico sizes:", sorted(check.info.get("sizes", [])))


if __name__ == "__main__":
    main()
