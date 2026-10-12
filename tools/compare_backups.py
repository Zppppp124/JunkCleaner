"""逐个检查备份的 Startup 段，找出真正未被污染的原始曲线。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, vfcurve  # noqa: E402


def main() -> int:
    bdir = core.data_dir() / "afterburner_backups"
    print(f"备份目录: {bdir}")
    print("=" * 96)
    print(f"{'文件':<50}{'Startup点':>9}{'Startup最大MHz':>14}"
          f"{'2850mV':>9}{'Defaults点':>11}")
    print("-" * 96)
    for b in sorted(bdir.glob("*.cfg")):
        s = vfcurve.read_curve(b, "Startup")
        d = vfcurve.read_curve(b, "Defaults")
        n_s = len(s.points) if s else 0
        n_d = len(d.points) if d else 0
        mx = max((p.freq_mhz for p in s.points), default=0) if s else 0
        v = s.voltage_for_freq(2850) if s else None
        print(f"{b.name[:48]:<50}{n_s:>9}{mx:>14.0f}"
              f"{(('%.0f' % v) if v else '-'):>9}{n_d:>11}")
    print("=" * 96)
    print("判定：Startup 点数 127 且最大频率 ~2940 才是原始曲线")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
