"""用正确的设备实例名重启 NVIDIA 显卡驱动，清除 Reliability 保护状态。"""

from __future__ import annotations

import subprocess
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from junkcleaner import gpu  # noqa: E402


def ps(script: str) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                       capture_output=True)
    return ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace").strip()


def main() -> int:
    print("=" * 80)
    print("[1] 找出 NVIDIA 显示设备的实例名")
    out = ps("Get-PnpDevice -Class Display | "
             "Where-Object { $_.FriendlyName -match 'NVIDIA' } | "
             "Select-Object Status,Class,FriendlyName,InstanceId | "
             "Format-List | Out-String")
    print(out)
    import re
    ids = re.findall(r"InstanceId\s*:\s*(\S+)", out)
    print(f"   实例名: {ids}")
    if not ids:
        print("   未找到，跳过驱动重载")
        return 1

    dev = ids[0]
    print("=" * 80)
    print(f"[2] 禁用 -> 启用  {dev}")
    print("   disable:", ps(f"pnputil /disable-device '{dev}' 2>&1"))
    time.sleep(3)
    print("   enable :", ps(f"pnputil /enable-device '{dev}' 2>&1"))
    time.sleep(8)

    print("=" * 80)
    print("[3] 复位后的状态")
    for i in range(4):
        st = gpu.read_state()
        print(f"   {i}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
              f"{st.temperature}°C  节流={st.throttle}")
        time.sleep(2)

    print("=" * 80)
    st = gpu.read_state()
    mask = int(st.throttle.replace("0x", "") or "0", 16) if st.throttle else 0
    if mask == 0:
        print("   ✔ Reliability 已清除")
    elif mask & 0x400:
        print("   ✖ Reliability 仍在，建议重启电脑（或断电 30 秒后开机）")
    else:
        print(f"   节流掩码 {st.throttle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
