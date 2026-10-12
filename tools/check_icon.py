"""检查生成图标的边缘是否残留水印/白边。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def lum(px) -> float:
    return 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    png = root / "junkcleaner" / "assets" / "app.png"
    ico = root / "junkcleaner" / "assets" / "app.ico"
    img = Image.open(png).convert("RGB")
    w, h = img.size
    print(f"app.png: {w} x {h}")

    # 底部 60 行里的亮像素（水印是白字）
    bright = 0
    coords = []
    for y in range(h - 60, h):
        for x in range(w):
            if lum(img.getpixel((x, y))) > 200:
                bright += 1
                coords.append((x, y))
    print(f"底部 60 行亮像素数(水印残留): {bright}")
    if coords:
        xs = [c[0] for c in coords]
        print(f"  横向分布: x {min(xs)}..{max(xs)}  "
              f"(图宽 {w}，水印会集中在右侧 x>{int(w*0.7)})")
        right_side = sum(1 for c in coords if c[0] > w * 0.7)
        print(f"  右侧亮像素: {right_side}")

    # 四角应为深色（无白边）
    corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)),
               img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
    print("四角亮度:", [round(lum(c)) for c in corners])

    # ICO 内含尺寸
    ico_img = Image.open(ico)
    print(f"app.ico 主尺寸: {ico_img.size}, "
          f"包含: {sorted(ico_img.info.get('sizes', []))}")

    # 水印只会在右侧；中央的亮像素是盾牌尖端光晕，属正常内容
    right_side = sum(1 for c in coords if c[0] > w * 0.7)
    ok = right_side == 0 and all(lum(c) < 120 for c in corners)
    if right_side:
        print("\n右侧仍有亮像素，可能是水印残留")
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
