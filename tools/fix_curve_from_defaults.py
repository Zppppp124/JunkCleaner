"""用 Defaults 段的完整曲线修复 Startup/Profile1（它们被压平了）。"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, gpu, gpu_load, vfcurve  # noqa: E402


def show(tag: str, c) -> None:
    if not c:
        print(f"  [{tag}] 读取失败")
        return
    pts = c.points
    print(f"  [{tag}] {len(pts)} 点  频率 {min(p.freq_mhz for p in pts):.0f}"
          f"~{max(p.freq_mhz for p in pts):.0f} MHz")
    for f in (2700, 2760, 2850, 2895):
        v = c.voltage_for_freq(f)
        print(f"        {f}MHz -> {v:.0f}mV" if v else f"        {f}MHz -> 无")


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    print(f"Profile: {prof.name}")
    print("=" * 78)
    print("[1] 修复前")
    for s in ("Startup", "Profile1", "Defaults"):
        show(s, vfcurve.read_curve(prof, s))

    # 备份当前状态
    bak = vfcurve.backup_profile(prof)
    print(f"\n已备份当前状态: {bak.name}")

    # 用 Defaults 的曲线覆盖 Startup 与 Profile1
    d = vfcurve.read_curve(prof, "Defaults")
    if d is None:
        print("读不到 Defaults，无法修复")
        return 1
    # 重写 hex：把 Defaults 的完整曲线写进另外两段
    full_hex = d.to_hex()
    text = prof.read_text(encoding="utf-8", errors="replace")
    import re
    for sec in ("Startup", "Profile1"):
        span = vfcurve._section_span(text, sec)
        if span is None:
            continue
        body = text[span[0]:span[1]]
        nb, n = re.subn(r"VFCurve=[0-9A-Fa-f]+", f"VFCurve={full_hex}",
                        body, count=1)
        if n:
            text = text[:span[0]] + nb + text[span[1]:]
            print(f"  已把 Defaults 曲线写入 [{sec}]")
    prof.write_text(text, encoding="utf-8")
    print(f"  应用: {vfcurve.reload_profile(1)}")
    time.sleep(3)

    print("=" * 78)
    print("[2] 修复后")
    for s in ("Startup", "Profile1", "Defaults"):
        show(s, vfcurve.read_curve(prof, s))

    print("=" * 78)
    print("[3] 锁 2850 并满载验证能否达到")
    gpu.reset_clocks()
    time.sleep(2)
    print("  lock:", gpu.lock_clocks(2850))
    loader = gpu_load.GpuStress()
    loader.start()
    try:
        time.sleep(5)
        seen = []
        for i in range(5):
            time.sleep(3)
            st = gpu.read_state()
            seen.append(st.clock_graphics)
            print(f"  {i}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
                  f"{st.temperature}°C  占用 {st.utilization}%  "
                  f"降频={st.throttle}")
    finally:
        loader.stop()
        time.sleep(2)

    print("=" * 78)
    best = max(seen) if seen else 0
    print(f"  实测最高 {best} MHz")
    if best >= 2800:
        print("  ✔ 修复成功：现在能接近 2850 了")
    else:
        print("  ✖ 仍受限，需要进一步排查")
    print(f"  复位: {gpu.reset_clocks()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
