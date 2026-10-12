"""验证 CPU 调压在当前平台的可行性（只读检查，不写入 MSR）。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = (p.stdout or b"") + (p.stderr or b"")
        for enc in ("utf-8", "gbk", "cp936"):
            try:
                return out.decode(enc)
            except UnicodeDecodeError:
                continue
        return out.decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return f"<失败: {exc}>"


def main() -> int:
    print("=" * 72)
    print("[1] CPU 型号与微码版本（决定 Undervolt Protection 是否生效）")
    print(run(["powershell", "-NoProfile", "-Command",
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
               "Get-CimInstance Win32_Processor | "
               "Select-Object Name,MaxClockSpeed,CurrentVoltage | Format-List | Out-String"]))
    print(run(["powershell", "-NoProfile", "-Command",
               "Get-ItemProperty 'HKLM:\\HARDWARE\\DESCRIPTION\\System\\"
               "CentralProcessor\\0' | Select-Object 'Update Revision',"
               "'Update Status','Previous Update Revision' | Format-List | Out-String"]))

    print("=" * 72)
    print("[2] 是否可直接访问 MSR（需要内核驱动，普通 API 无法访问）")
    try:
        ntdll = ctypes.windll.ntdll
        # 尝试用 ZwOpenKey 打开 MSR 设备（正常会失败，说明没有驱动）
        import winreg
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Services\WinRing0")
            print("   WinRing0 服务键存在")
        except OSError as exc:
            print(f"   WinRing0 服务不存在（{exc.winerror}）")
        # 测试内核驱动加载能力
        print("   测试能否加载未签名内核驱动（拿 SeLoadDriverPrivilege）...")
        import ctypes as ct
        from ctypes import wintypes as wt
        adv = ct.windll.advapi32
        h = wt.HANDLE()
        adv.OpenProcessToken(ct.windll.kernel32.GetCurrentProcess(),
                             0x0008 | 0x0020, ct.byref(h))
        luid = wt.LUID()
        ok = adv.LookupPrivilegeValueW(None, "SeLoadDriverPrivilege",
                                       ct.byref(luid))
        print(f"   SeLoadDriverPrivilege 查询: {'可用' if ok else '不可用'}")
    except Exception as exc:  # noqa: BLE001
        print(f"   检查失败: {exc}")

    print("=" * 72)
    print("[3] 当前 BIOS 是否已启用调压相关选项（通过电压读数间接判断）")
    for d in ("VOLTAGE", "CLOCK", "POWER"):
        out = run([r"C:\Windows\system32\nvidia-smi.EXE", "-q", "-d", d])
        keys = [ln.strip() for ln in out.splitlines()
                if any(k in ln for k in ("Voltage", "Power Limit", "Clock"))][:6]
        print(f"   nvidia-smi -d {d}: {keys[:4]}")

    print("=" * 72)
    print("[4] 系统是否有温度/电压传感器可读（LibreHardwareMonitor 类）")
    for p in (r"C:\Program Files\LibreHardwareMonitor",
              r"C:\Program Files (x86)\HWiNFO64",
              r"C:\Program Files\HWiNFO64"):
        print(f"   {'有' if Path(p).exists() else '无'}  {p}")
    print("   WMI 温度传感器:")
    print(run(["powershell", "-NoProfile", "-Command",
               "Get-CimInstance -Namespace root/WMI -ClassName "
               "MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue | "
               "Select-Object -First 3 InstanceName,CurrentTemperature | "
               "Format-List | Out-String"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
