"""实测自适应降压搜索（短时长版本，用于验证机制）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import undervolt, vfcurve  # noqa: E402


def main() -> int:
    freq = int(sys.argv[1]) if len(sys.argv) > 1 else 2760
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    steps = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    print(f"目标 {freq}MHz，单档 {seconds}s，最多 {steps} 档")
    print("=" * 74)
    engine = undervolt.AdaptiveUndervolt(
        freq=freq, test_seconds=seconds, step_mv=25.0, floor_mv=800.0,
        max_steps=steps, progress=lambda m: print("  ", m))
    res = engine.run()
    print("=" * 74)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2,
                     default=str))

    # 确认最终停在稳定配置
    prof = vfcurve.find_gpu_profile()
    if prof:
        c = vfcurve.read_curve(prof, "Startup")
        if c:
            print(f"\n最终 {freq}MHz 电压: {c.voltage_for_freq(freq)} mV")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
