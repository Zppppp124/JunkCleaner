"""从源图生成应用图标（.ico + .png）。

处理内容：
  1. 裁掉四周白边，只保留深色方框；
  2. 裁掉底部「豆包AI生成」水印（它与方框底部重叠）；
  3. 居中裁成正方形；
  4. 输出多尺寸 .ico（16~256）与预览 PNG。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_SRC = (r"C:\Users\Admin\AppData\Local\Temp"
               r"\codex-clipboard-bd825c78-6aca-4f29-ac77-76036f8caed4.png")
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "junkcleaner" / "assets"

# 深色方框边界（由 tools\inspect_icon_src.py 实测得到）
FRAME = (231, 140, 1818, 1913)   # left, top, right, bottom（含边界）
# 水印自 y≈1802 开始（方框底部 1913），裁到 1800 即可去掉
WATERMARK_TOP = 1800

ICON_SIZES = [256, 128, 64, 48, 32, 24, 16]


def build(src: Path) -> tuple[Path, Path]:
    img = Image.open(src).convert("RGBA")
    left, top, right, bottom = FRAME
    # 1) 裁掉白边 + 2) 裁掉水印
    crop_bottom = min(bottom, WATERMARK_TOP)
    box = (left, top, right + 1, crop_bottom)
    img = img.crop(box)
    w, h = img.size
    print(f"裁切后: {w} x {h}")
    # 3) 居中裁成正方形
    side = min(w, h)
    x0 = (w - side) // 2
    y0 = (h - side) // 2
    img = img.crop((x0, y0, x0 + side, y0 + side))
    print(f"正方形: {img.size}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / "app.png"
    ico_path = OUT_DIR / "app.ico"

    img.save(png_path, "PNG")
    # 4) 多尺寸 ICO
    img.save(ico_path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    print(f"已生成: {png_path}")
    print(f"已生成: {ico_path}")

    # 生成一张预览图（各尺寸平铺，便于肉眼检查清晰度）
    preview = Image.new("RGBA", (560, 300), (244, 241, 251, 255))
    x = 20
    for s in (256, 128, 64, 48, 32, 16):
        thumb = img.resize((s, s), Image.LANCZOS)
        preview.paste(thumb, (x, 20), thumb)
        x += s + 16
        if x > 520:
            break
    draw = ImageDraw.Draw(preview)
    draw.text((20, 275), "JunkCleaner icon preview  (256/128/64/48/32/16)",
              fill=(58, 51, 82))
    preview_path = ROOT / "tools" / "_icon_preview.png"
    preview.save(preview_path)
    print(f"预览: {preview_path}")
    return ico_path, png_path


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(DEFAULT_SRC)
    if not src.exists():
        print(f"找不到源图: {src}")
        return 1
    build(src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
