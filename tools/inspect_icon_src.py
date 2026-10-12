"""探测源图的深色方框边界与水印位置。"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Users\Admin\AppData\Local\Temp"
        r"\codex-clipboard-bd825c78-6aca-4f29-ac77-76036f8caed4.png")
    img = Image.open(src).convert("RGB")
    w, h = img.size
    print(f"尺寸: {w} x {h}")

    # 采样四角，判断白边
    print("四角颜色:", img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
          img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1)))

    # 找深色区域的边界（亮度阈值）
    def lum(px: tuple[int, int, int]) -> float:
        return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]

    left, right, top, bottom = w, 0, h, 0
    step = 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            if lum(img.getpixel((x, y))) < 120:
                left = min(left, x)
                right = max(right, x)
                top = min(top, y)
                bottom = max(bottom, y)
    print(f"深色区域: x {left}..{right}  y {top}..{bottom}")
    print(f"  宽 {right-left+1}  高 {bottom-top+1}")

    # 水印大概位置：右下角区域的最亮像素（白字）
    wx0, wy0 = int(w * 0.72), int(h * 0.88)
    bright = []
    for y in range(wy0, h, 2):
        for x in range(wx0, w, 2):
            px = img.getpixel((x, y))
            if lum(px) > 200:
                bright.append((x, y))
    if bright:
        xs = [p[0] for p in bright]
        ys = [p[1] for p in bright]
        print(f"右下亮像素(疑似水印): x {min(xs)}..{max(xs)}  "
              f"y {min(ys)}..{max(ys)}  数量 {len(bright)}")
        print(f"  水印是否落在深色区内: "
              f"{min(ys) <= bottom and min(xs) <= right}")
    else:
        print("右下未发现亮像素")

    # 用中线扫描精确定位深色方框四条边（避开右下角水印）
    def lum2(px):
        return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]

    cy, cx = h // 2, w // 2
    left_e = next((x for x in range(w) if lum2(img.getpixel((x, cy))) < 120), None)
    right_e = next((x for x in range(w - 1, -1, -1)
                    if lum2(img.getpixel((x, cy))) < 120), None)
    top_e = next((y for y in range(h) if lum2(img.getpixel((cx, y))) < 120), None)
    bottom_e = next((y for y in range(h - 1, -1, -1)
                     if lum2(img.getpixel((cx, y))) < 120), None)
    print(f"中线扫描边界: left={left_e} right={right_e} "
          f"top={top_e} bottom={bottom_e}")
    if None not in (left_e, right_e, top_e, bottom_e):
        print(f"  方框尺寸: {right_e-left_e+1} x {bottom_e-top_e+1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
