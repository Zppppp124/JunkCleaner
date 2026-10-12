"""从最早的备份还原被污染的 V/F 曲线。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, vfcurve  # noqa: E402


def show(tag: str, c) -> None:
    if not c:
        print(f"  [{tag}] 读取失败")
        return
    bad = [p for p in c.points if p.freq_mhz > vfcurve.MAX_PLAUSIBLE_MHZ]
    v = c.voltage_for_freq(2850)
    print(f"  [{tag}] {len(c.points)} 点  坏点{len(bad)}  "
          f"2850MHz->{v:.0f}mV" if v else f"  [{tag}] {len(c.points)} 点")


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    print(f"Profile: {prof}")
    print("=" * 78)
    print("[1] 当前状态")
    for sec in ("Startup", "Defaults"):
        show(sec, vfcurve.read_curve(prof, sec))

    print("=" * 78)
    print("[2] 可用备份（按时间）")
    bdir = core.data_dir() / "afterburner_backups"
    backs = sorted(bdir.glob("*.cfg")) if bdir.exists() else []
    for i, b in enumerate(backs):
        c = vfcurve.read_curve(b, "Defaults")
        n = len(c.points) if c else 0
        print(f"  [{i}] {b.name}  {b.stat().st_size} B  Defaults {n} 点")

    # 选 Defaults 点数最多、且 Startup 未被压平的最早备份
    good = None
    for b in backs:
        c = vfcurve.read_curve(b, "Startup")
        d = vfcurve.read_curve(b, "Defaults")
        if not c or not d:
            continue
        # Startup 正常应有递增曲线（不是全 800）
        volts = {round(p.voltage_mv) for p in c.points}
        if len(volts) > 10 and len(c.points) >= 120:
            good = b
            break
    if good is None and backs:
        good = backs[0]
    print("=" * 78)
    print(f"[3] 选用备份还原: {good.name if good else '（无）'}")
    if good:
        shutil.copy2(good, prof)
        print("    已写回")
        vfcurve.reload_profile(1)
        import time
        time.sleep(3)
        print("[4] 还原后")
        for sec in ("Startup", "Defaults"):
            show(sec, vfcurve.read_curve(prof, sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
