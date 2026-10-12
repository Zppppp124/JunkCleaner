"""探测 CPU 风扇控制通道。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def ps(script: str) -> str:
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
                       capture_output=True)
    return ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace").strip()


def main() -> int:
    print("=" * 70)
    print("[1] 机箱/CPU 风扇（WMI Win32_Fan）")
    print(ps("Get-CimInstance Win32_Fan | Select-Object Name,DeviceID,"
             "DesiredSpeed,Status,ActiveCooling | Format-List | Out-String"))

    print("=" * 70)
    print("[2] 温度探针（Win32_TemperatureProbe）")
    print(ps("Get-CimInstance Win32_TemperatureProbe | Select-Object Name,"
             "DeviceID,CurrentReading,Status | Format-List | Out-String") or "（无）")

    print("=" * 70)
    print("[3] ACPI 热区（MSAcpi_ThermalZoneTemperature）")
    print(ps("Get-CimInstance -Namespace root/WMI -ClassName "
             "MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue | "
             "Select-Object InstanceName,CurrentTemperature | Format-List | Out-String")
          or "（无）")

    print("=" * 70)
    print("[4] ASUS 相关服务/驱动")
    print(ps("Get-Service | Where-Object { $_.Name -match 'ASUS|AsIO|ATK|AURA' } | "
             "Select-Object Name,Status | Format-Table -AutoSize | Out-String") or "（无）")
    for d in (r"C:\Windows\System32\drivers\AsIO3.sys",
              r"C:\Windows\System32\drivers\AsIO2.sys",
              r"C:\Windows\System32\AsusCertService"):
        p = Path(d)
        print(f"   {'有' if p.exists() else '无'}  {d}")

    print("=" * 70)
    print("[5] 已安装的华硕软件")
    print(ps("Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
             "Uninstall\\*','HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\"
             "CurrentVersion\\Uninstall\\*' -ErrorAction SilentlyContinue | "
             "Where-Object { $_.DisplayName -match 'ASUS|Armoury|AURA|AI Suite' } | "
             "Select-Object DisplayName,InstallLocation | Format-List | Out-String")
          or "（无）")

    print("=" * 70)
    print("[6] 嵌入式控制器 / IO 访问驱动候选")
    for d in (r"C:\Windows\System32\drivers\PawnIO.sys",
              r"C:\Windows\System32\drivers\WinRing0x64.sys",
              r"C:\Windows\System32\drivers\inpoutx64.sys",
              r"C:\Windows\System32\drivers\RTCore64.sys"):
        p = Path(d)
        print(f"   {'有' if p.exists() else '无'}  {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
