"""对比 Startup / Profile1 / Defaults 三个段的曲线，确认哪个是有效数据。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import vfcurve  # noqa: E402


def summarize(section: str) -> None:
    prof = vfcurve.find_gpu_profile()
    c = vfcurve.read_curve(prof, section)
    if not c:
        print(f"  [{section}] 读不到")
        return
    freqs = [p.freq_mhz for p in c.points]
    volts = [p.voltage_mv for p in c.points]
    # 统计异常值
    over = [p for p in c.points if p.freq_mhz > 3200]
    print(f"  [{section}] {len(c.points)} 点  "
          f"频率 {min(freqs):.0f}~{max(freqs):.0f}  "
          f"电压 {min(volts):.0f}~{max(volts):.0f}")
    print(f"       超出 3200MHz 的异常点: {len(over)}"
          + (f"  值={sorted({int(p.freq_mhz) for p in over})}" if over else ""))
    # 2850 对应的电压
    v = c.voltage_for_freq(2850)
    print(f"       2850MHz -> {v:.0f} mV" if v else "       2850MHz -> 无匹配")


def main() -> int:
    print("=" * 78)
    print("三个段的曲线对比")
    for s in ("Startup", "Profile1", "Defaults"):
        summarize(s)
    print("=" * 78)
    print("判断：频率超过显卡上限（3150MHz）的点必然是坏数据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
