"""对比各段曲线，确认降压是否污染了数据。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import vfcurve  # noqa: E402


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    print(f"Profile: {prof.name}")
    print("=" * 78)
    for sec in ("Startup", "Profile1", "Defaults"):
        c = vfcurve.read_curve(prof, sec)
        if not c:
            print(f"  [{sec}] 读取失败")
            continue
        bad = [p for p in c.points if p.freq_mhz > vfcurve.MAX_PLAUSIBLE_MHZ]
        print(f"  [{sec}] {len(c.points)} 点，坏点 {len(bad)}")
        for f in (2700, 2760, 2835, 2850, 2895):
            v = c.voltage_for_freq(f)
            near = c.nearest_to_freq(f)
            print(f"      {f:>5}MHz -> {v:7.1f} mV"
                  if v else f"      {f:>5}MHz -> 无")

    print("=" * 78)
    print("按新逻辑选出的最优段：")
    c, sec = vfcurve.read_best_curve(prof)
    if c:
        print(f"  使用 [{sec}]，{len(c.points)} 点，"
              f"频率 {min(p.freq_mhz for p in c.points):.0f} ~ "
              f"{max(p.freq_mhz for p in c.points):.0f} MHz")
        for f in (2700, 2760, 2835, 2850, 2895):
            v = c.voltage_for_freq(f)
            print(f"      {f:>5}MHz -> {v:.1f} mV" if v else f"      {f} 无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
