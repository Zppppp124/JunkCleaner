"""把 GPU 恢复到干净状态：曲线复位 + 时钟复位 + 驱动重载。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, gpu, vfcurve  # noqa: E402


def ps(script: str) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                       capture_output=True)
    return (p.stdout or b"").decode("utf-8", "replace").strip()


def show_curve(tag: str) -> None:
    prof = vfcurve.find_gpu_profile()
    print(f"  [{tag}]")
    for sec in ("Startup", "Defaults"):
        c = vfcurve.read_curve(prof, sec)
        if not c:
            continue
        v = c.voltage_for_freq(2760)
        mx = max(p.freq_mhz for p in c.points)
        print(f"     {sec:<10} {len(c.points):>3}点  最高{mx:.0f}MHz  "
              f"2760MHz->{v:.0f}mV" if v else "")


def main() -> int:
    print("=" * 80)
    print("[1] 还原前的曲线")
    show_curve("before")

    print("=" * 80)
    print("[2] 用最早的原始备份还原曲线")
    bdir = core.data_dir() / "afterburner_backups"
    backs = sorted(bdir.glob("*.cfg"))
    # 找 Startup 点数最多、电压跨度最大的那个（= 未被压平的原始曲线）
    best = None
    best_score = -1
    for b in backs:
        c = vfcurve.read_curve(b, "Startup")
        if not c:
            continue
        span = max(p.voltage_mv for p in c.points) - min(p.voltage_mv for p in c.points)
        score = len(c.points) * 1000 + span
        if score > best_score:
            best_score = score
            best = b
    if best:
        import shutil
        shutil.copy2(best, vfcurve.find_gpu_profile())
        print(f"   已还原自: {best.name}")
        vfcurve.reload_profile(1)
        time.sleep(3)
    print("=" * 80)
    print("[3] 还原后的曲线")
    show_curve("after")

    print("=" * 80)
    print("[4] 时钟/功耗复位")
    print("   reset clocks:", gpu.reset_clocks())
    print("   power 295:", gpu.set_power_limit(295))

    print("=" * 80)
    print("[5] 重启显卡驱动（重置 Reliability 保护状态）")
    print(ps("pnputil /disable-device \"PCI\\VEN_10DE*\" 2>&1; "
             "Start-Sleep 2; pnputil /enable-device \"PCI\\VEN_10DE*\" 2>&1")
          or "（尝试完成）")
    time.sleep(6)

    print("=" * 80)
    print("[6] 复位后状态")
    st = gpu.read_state()
    print(f"   频率 {st.clock_graphics} MHz  功耗 {st.power_draw:.0f}W  "
          f"{st.temperature}°C  节流={st.throttle}")
    print(f"   建议：如果 Reliability 仍在，需要重启电脑")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
