"""验证 V/F 曲线读取与「只改目标点」的精确性。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import vfcurve  # noqa: E402


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    print(f"Profile: {prof}")
    if prof is None:
        print("未找到 Profile")
        return 1

    curve = vfcurve.read_curve(prof, "Startup")
    if curve is None:
        print("读取失败")
        return 1
    print(f"曲线点数: {len(curve.points)}")
    print(f"最高频率: {curve.max_freq} MHz   最高电压: {curve.max_voltage} mV")

    print("\n前 6 个点:")
    for p in curve.points[:6]:
        print(f"  #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz")
    print("后 6 个点:")
    for p in curve.points[-6:]:
        print(f"  #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz")

    print("\n目标频率 2760MHz 附近:")
    for p in curve.points_near_freq(2760, 60):
        print(f"  #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz")
    print(f"  最近点电压: {curve.voltage_for_freq(2760)} mV")

    print(f"\n全曲线分布（每 12 个点采样一次）:")
    for p in curve.points[::12]:
        print(f"  #{p.index:<3} {p.voltage_mv:7.1f} mV  {p.freq_mhz:7.1f} MHz")
    # 用电压窗口做降压测试（高频段点很稀疏，按电压找更可靠）
    original = bytes(curve.raw)
    target_freq = 2760.0
    print(f"\n=== 测试把 {target_freq}MHz 附近的点降到 900mV ===")
    window = 200.0
    before = [(p.index, p.voltage_mv, p.freq_mhz)
              for p in curve.points_near_freq(target_freq, window)]
    changed = curve.apply_flat_voltage_near(target_freq, 900.0, window)
    after = [(p.index, p.voltage_mv, p.freq_mhz)
             for p in curve.points_near_freq(target_freq, window)]
    print(f"  改动点数: {len(changed)}  序号: {changed}")
    for b, a in zip(before, after):
        print(f"   #{b[0]:<3} {b[1]:.1f} -> {a[1]:.1f} mV   (freq {b[2]:.0f})")
    diff = sum(1 for x, y in zip(original, curve.raw) if x != y)
    print(f"  字节差异: {diff} / {len(original)}  "
          f"（每点应只改 4 字节，共 {len(changed) * 4} 字节）")

    # 检查非目标点未被改动
    other_changed = [p.index for p in curve.points
                     if p.index not in changed
                     and abs(p.voltage_mv
                             - vfcurve.VfCurve(original).points[p.index].voltage_mv) > 1e-6]
    print(f"  非目标点被误改: {other_changed or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
