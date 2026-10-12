"""诊断「设定 2850 却停在 2760」的原因。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, vfcurve  # noqa: E402


def dump_curve() -> None:
    prof = vfcurve.find_gpu_profile()
    c = vfcurve.read_curve(prof, "Startup")
    if not c:
        print("  读不到曲线")
        return
    print(f"  曲线点数 {len(c.points)}，Profile: {prof.name}")
    print("  高电压段（最后 30 个点）：")
    for p in c.points[-30:]:
        print(f"    #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz")
    freqs = sorted(p.freq_mhz for p in c.points)
    print(f"  频率范围: {freqs[0]:.0f} ~ {freqs[-1]:.0f} MHz")
    # 有没有 2850 附近的点
    near = [p for p in c.points if 2750 <= p.freq_mhz <= 2950]
    print(f"  2750~2950MHz 之间的点: {[(p.index,int(p.voltage_mv),int(p.freq_mhz)) for p in near]}")


def main() -> int:
    print("=" * 78)
    print("[1] 当前 GPU 状态")
    st = gpu.read_state()
    print(json.dumps(st.to_dict(), ensure_ascii=False, indent=2))

    print("=" * 78)
    print("[2] 当前 V/F 曲线")
    dump_curve()

    print("=" * 78)
    print("[3] 复位时钟，观察原始行为")
    print("  reset:", gpu.reset_clocks())
    time.sleep(2)
    loader = None
    try:
        from junkcleaner import gpu_load
        loader = gpu_load.GpuStress()
        loader.start()
        time.sleep(6)
        st2 = gpu.read_state()
        print(f"  满载（无锁频）: {st2.clock_graphics} MHz  {st2.power_draw:.0f}W  "
              f"占用 {st2.utilization}%  降频={st2.throttle}")
    finally:
        if loader:
            loader.stop()
    time.sleep(2)

    print("=" * 78)
    print("[4] 锁到 2850MHz，看实际能不能到")
    r = gpu.lock_clocks(2850)
    print("  lock:", r)
    time.sleep(2)
    st3 = gpu.read_state()
    print(f"  锁频后（空闲）: {st3.clock_graphics} MHz  locked={st3.locked_graphics}")
    loader = None
    try:
        from junkcleaner import gpu_load
        loader = gpu_load.GpuStress()
        loader.start()
        for i in range(6):
            time.sleep(3)
            s = gpu.read_state()
            print(f"  满载 {i}: {s.clock_graphics} MHz  {s.power_draw:.0f}W  "
                  f"{s.temperature}°C  占用 {s.utilization}%  降频={s.throttle}")
    finally:
        if loader:
            loader.stop()

    print("=" * 78)
    print("[5] 分析")
    st4 = gpu.read_state()
    print(f"  锁定值      : {st4.locked_graphics} MHz")
    print(f"  实际上限    : {st4.clock_max} MHz")
    print(f"  功耗墙      : {st4.power_limit:.0f} / 上限 {st4.power_max:.0f} W")
    print(f"  功耗状态    : {st4.power_draw:.0f} W")
    print(f"  降频原因    : {st4.throttle}")

    print("=" * 78)
    print("[6] 复位")
    print("  reset:", gpu.reset_clocks())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
