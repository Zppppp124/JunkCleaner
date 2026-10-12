"""查清 Reliability 节流的成因，以及是否能通过复位清除。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load, vfcurve  # noqa: E402

SMI = r"C:\Windows\system32\nvidia-smi.EXE"


def ps(script: str) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                       capture_output=True)
    return (p.stdout or b"").decode("utf-8", "replace").strip()


def load_once(tag: str, secs: int = 10) -> int:
    loader = gpu_load.GpuStress()
    loader.start()
    try:
        time.sleep(3)
        cl = []
        for _ in range(3):
            time.sleep(2.5)
            st = gpu.read_state()
            cl.append(st.clock_graphics)
            print(f"    {tag}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
                  f"{st.temperature}°C  节流={st.throttle}")
        return max(cl) if cl else 0
    finally:
        loader.stop()
        time.sleep(2)


def main() -> int:
    print("=" * 80)
    print("[1] 事件日志里的显示驱动错误（TDR / 驱动重置）")
    print(ps("Get-WinEvent -FilterHashtable @{LogName='System';"
             "ProviderName='Display'} -MaxEvents 8 -ErrorAction SilentlyContinue | "
             "Select-Object TimeCreated,Id,LevelDisplayName,Message | "
             "Format-List | Out-String")[:2000] or "（无 Display 事件）")

    print("=" * 80)
    print("[2] 是否有 nvlddmkm 错误")
    print(ps("Get-WinEvent -FilterHashtable @{LogName='System';"
             "ProviderName='nvlddmkm'} -MaxEvents 5 -ErrorAction SilentlyContinue | "
             "Select-Object TimeCreated,Id,Message | Format-List | Out-String")[:1500]
          or "（无 nvlddmkm 事件）")

    print("=" * 80)
    print("[3] 当前电源/供电相关设置")
    print(f"   PCIe 链路状态: "
          f"{ps('(Get-PnpDevice -Class System -Status OK | Where-Object {$_.FriendlyName -match \'PCI\'} | Select-Object -First 1).FriendlyName')}")
    print("   电源方案:")
    print("   " + ps("powercfg /getactivescheme"))

    print("=" * 80)
    print("[4] 执行完整复位（GPU 复位 + 时钟复位 + 功耗墙复位）")
    print("   reset clocks:", gpu.reset_clocks())
    st = gpu.read_state()
    print("   power limit:", gpu.set_power_limit(int(st.power_max)))
    time.sleep(2)
    print("   power back:", gpu.set_power_limit(295))
    time.sleep(3)

    print("=" * 80)
    print("[5] 复位后测负载（看可靠性节流是否消失）")
    c = load_once("复位后")
    print(f"   -> {c} MHz")

    print("=" * 80)
    print("[6] 检查显卡当前 BIOS 是否被改过（OC 版本判定）")
    print(ps(f"& '{SMI}' -q -d BOARD | Select-String -Pattern "
             "'Product|Board|Serial|VBIOS|Version' | Out-String"))

    print("=" * 80)
    print("[7] 结论")
    print(f"   负载频率: {c} MHz")
    print(f"   节流原因: {gpu.read_state().throttle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
