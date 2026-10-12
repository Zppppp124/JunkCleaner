"""最后排查：虚拟显示适配器 / 显示器刷新率 是否限制 GPU 频率。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load  # noqa: E402

SMI = r"C:\Windows\system32\nvidia-smi.EXE"


def ps(script: str) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                       capture_output=True)
    return (p.stdout or b"").decode("utf-8", "replace").strip()


def main() -> int:
    print("=" * 80)
    print("[1] 显示适配器")
    print(ps("Get-CimInstance Win32_VideoController | "
             "Select-Object Name,CurrentHorizontalResolution,"
             "CurrentVerticalResolution,CurrentRefreshRate,Status | "
             "Format-Table -AutoSize | Out-String"))

    print("=" * 80)
    print("[2] 显示器")
    print(ps("Get-CimInstance -Namespace root/wmi -ClassName "
             "WmiMonitorBasicDisplayParams -ErrorAction SilentlyContinue | "
             "Select-Object InstanceName,MaxHorizontalImageSize,"
             "MaxVerticalImageSize | Format-Table -AutoSize | Out-String"))

    print("=" * 80)
    print("[3] nvidia-smi 功耗与节流详情")
    p = subprocess.run([SMI, "-q", "-d", "POWER,PERFORMANCE"],
                       capture_output=True)
    txt = (p.stdout or b"").decode("utf-8", "replace")
    for line in txt.splitlines():
        if any(k in line for k in ("Power", "Limit", "Performance", "Slowdown",
                                   "Throttle", "Clock")):
            print("   ", line.strip())

    print("=" * 80)
    print("[4] 全量节流原因（-q -d PERFORMANCE）")
    print(txt[txt.find("Performance State"):][:1200]
          if "Performance State" in txt else "（无）")

    print("=" * 80)
    print("[5] 加载 GPU 并连续观察 20 秒（看是否最终会升频）")
    gpu.reset_clocks()
    time.sleep(2)
    loader = gpu_load.GpuStress()
    loader.start()
    try:
        time.sleep(3)
        for i in range(7):
            time.sleep(3)
            st = gpu.read_state()
            print(f"   {i}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
                  f"{st.temperature}°C  {st.utilization}%  节流={st.throttle}")
    finally:
        loader.stop()
        time.sleep(2)

    print("=" * 80)
    print("[6] 直接查询节流原因位掩码")
    p2 = subprocess.run([SMI, "--query-gpu=clocks_throttle_reasons.active,"
                         "clocks_throttle_reasons.gpu_idle,"
                         "clocks_throttle_reasons.sw_power_cap,"
                         "clocks_throttle_reasons.hw_slowdown,"
                         "clocks_throttle_reasons.hw_thermal_slowdown,"
                         "clocks_throttle_reasons.sw_thermal_slowdown,"
                         "clocks_throttle_reasons.hw_power_brake_slowdown",
                         "--format=csv"], capture_output=True)
    print("   " + (p2.stdout or b"").decode("utf-8", "replace").strip().replace("\n", "\n   "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
