"""逆向 Afterburner 的 VFCurve 十六进制格式。

思路：在多种「偏移 + 步长」组合下扫描 float32，找出能形成
单调递增电压序列（800~1200mV）与频率序列（1000~3500MHz）的解读方式。
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

CFG = Path(r"D:\Program Files (x86)\MSI Afterburner\Profiles"
           r"\VEN_10DE&DEV_2689&SUBSYS_18D410DE&REV_A1&BUS_1&DEV_0&FN_0.cfg")


def read_curve(cfg: Path, section: str) -> bytes:
    text = cfg.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"\[{re.escape(section)}\](.*?)(?=\n\[|\Z)", text, re.S)
    if not m:
        return b""
    body = m.group(1)
    m2 = re.search(r"VFCurve=([0-9A-Fa-f]+)", body)
    if not m2:
        return b""
    return bytes.fromhex(m2.group(1))


def f32(data: bytes, off: int) -> float:
    if off + 4 > len(data):
        return float("nan")
    return struct.unpack_from("<f", data, off)[0]


def main() -> int:
    cfg = Path(sys.argv[1]) if len(sys.argv) > 1 else CFG
    data = read_curve(cfg, "Defaults")
    print(f"文件: {cfg.name}")
    print(f"Defaults VFCurve 字节数: {len(data)}")
    hexlen = len(data) * 2
    print(f"（对应十六进制长度 {hexlen}）")
    print("=" * 74)

    # 先看开头 64 字节
    print("前 64 字节:")
    for i in range(0, min(64, len(data)), 16):
        chunk = data[i:i + 16]
        hexs = " ".join(f"{b:02X}" for b in chunk)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {i:04X}  {hexs:<47}  {txt}")

    print("=" * 74)
    # 扫描：找「连续多个递增 float」的组合
    best: list[tuple[int, int, int, float, float]] = []
    for off in range(0, 32):
        for stride in (4, 8, 12, 16, 20, 24, 32):
            vals: list[float] = []
            pos = off
            while pos + 4 <= len(data) and len(vals) < 200:
                v = f32(data, pos)
                if v != v or v == 0.0:      # NaN 或 0 视为空
                    break
                vals.append(v)
                pos += stride
            if len(vals) < 50:
                continue
            # 是否单调不减
            inc = all(b >= a - 1e-6 for a, b in zip(vals, vals[1:]))
            if not inc:
                continue
            if vals[0] < 300 or vals[-1] > 4000:
                continue
            best.append((off, stride, len(vals), vals[0], vals[-1]))

    print("候选解读（偏移, 步长, 个数, 首值, 末值）:")
    for row in sorted(best, key=lambda r: -r[2])[:12]:
        print(f"  off={row[0]:<3} stride={row[1]:<3} n={row[2]:<4} "
              f"first={row[3]:.1f} last={row[4]:.1f}")
    if not best:
        print("  未找到单调 float 序列，尝试其它解读")

    print("=" * 74)
    print("按 off=0/1/2/3 直接打印前 20 个 float:")
    for off in range(4):
        vals = [f32(data, off + i * 4) for i in range(20)]
        print(f"  off={off}: " + ", ".join(f"{v:.1f}" for v in vals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
