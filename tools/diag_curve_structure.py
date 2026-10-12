"""看清 V/F 曲线的真实结构：哪个区间是有效数据。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import vfcurve  # noqa: E402


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    c = vfcurve.read_curve(prof, "Defaults")
    print(f"Defaults 曲线：{len(c.points)} 点")
    print("=" * 78)
    print("完整曲线（每 2 个点一行，标出频率跳变处）")
    prev = None
    for p in c.points:
        jump = ""
        if prev is not None and p.freq_mhz - prev > 200:
            jump = f"   <<<< 跳变 +{p.freq_mhz - prev:.0f} MHz"
        print(f"  #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz{jump}")
        prev = p.freq_mhz

    print("=" * 78)
    print("按频率分段统计")
    segs: list[tuple[float, float, int]] = []
    start = c.points[0].freq_mhz
    last = start
    count = 1
    for p in c.points[1:]:
        if abs(p.freq_mhz - last) > 200 or p.freq_mhz < last:
            segs.append((start, last, count))
            start = p.freq_mhz
            count = 0
        last = p.freq_mhz
        count += 1
    segs.append((start, last, count))
    for a, b, n in segs:
        print(f"  {a:7.0f} ~ {b:7.0f} MHz   {n} 个点")

    print("=" * 78)
    print("结论")
    valid = [p for p in c.points if p.freq_mhz <= 3200]
    junk = [p for p in c.points if p.freq_mhz > 3200]
    print(f"  有效点（<=3200MHz）: {len(valid)}  最高 {max(p.freq_mhz for p in valid):.0f}")
    print(f"  可疑点（>3200MHz） : {len(junk)}   值 = "
          f"{sorted({int(p.freq_mhz) for p in junk})}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
