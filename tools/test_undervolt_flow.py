"""完整降压闭环验证：改曲线 -> 应用 -> 校验 -> 还原。

注意：此脚本会真实修改 Afterburner Profile 并应用，
但会先备份、结束时还原。
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, gpu, vfcurve  # noqa: E402


def main() -> int:
    prof = vfcurve.find_gpu_profile()
    print(f"Profile: {prof}")
    if prof is None:
        return 1

    # 1) 备份
    backup = vfcurve.backup_profile(prof)
    print(f"备份: {backup}")

    try:
        # 2) 读取原始曲线
        curve = vfcurve.read_curve(prof, "Startup")
        if curve is None:
            print("读取失败")
            return 1
        print(f"\n原始曲线: {len(curve.points)} 点, "
              f"最高 {curve.max_freq}MHz @ {curve.max_voltage}mV")

        target = 2760.0
        orig_v = curve.voltage_for_freq(target)
        print(f"目标 {target}MHz 原始电压: {orig_v} mV")

        # 3) 降压（小幅度试探，避免不稳）
        new_mv = (orig_v or 950.0) - 25.0
        window = 200.0
        changed = curve.apply_flat_voltage_near(target, new_mv, window)
        print(f"降压到 {new_mv}mV，改动点: {changed}")
        if not changed:
            print("没有可降的点，终止")
            return 1

        # 4) 写入 + 应用
        print(f"\n写入: {vfcurve.write_curve(prof, curve)}")
        print(f"应用 Profile: {vfcurve.reload_profile(1)}")
        time.sleep(3)

        # 5) 读回校验
        check = vfcurve.read_curve(prof, "Startup")
        got = check.voltage_for_freq(target) if check else None
        print(f"\n回读 {target}MHz 电压: {got} mV")
        ok = got is not None and abs(got - new_mv) < 1.0
        print(f"写入生效: {'是' if ok else '否'}")

        # 6) GPU 状态
        st = gpu.read_state()
        print(f"GPU: {st.clock_graphics}MHz {st.temperature}°C {st.power_draw:.0f}W")

    finally:
        # 7) 还原
        print(f"\n=== 还原 ===\n{vfcurve.restore_profile(backup, prof)}")
        vfcurve.reload_profile(1)
        time.sleep(2)
        back = vfcurve.read_curve(prof, "Startup")
        if back:
            print(f"还原后 {target}MHz 电压: {back.voltage_for_freq(target)} mV")

    # 校验还原是否与备份字节一致
    same = prof.read_bytes() == backup.read_bytes()
    print(f"还原后与备份完全一致: {same}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
