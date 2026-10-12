"""侦察硬件与可用的调优接口。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], timeout: int = 30) -> str:
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


def ps(script: str) -> str:
    return run(["powershell", "-NoProfile", "-Command",
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script])


def main() -> int:
    print("=" * 70)
    print("操作系统")
    print(ps("$o=Get-CimInstance Win32_OperatingSystem;"
             "'{0}|{1}|Build {2}' -f $o.Caption,$o.Version,$o.BuildNumber"))

    print("=" * 70)
    print("CPU")
    print(ps("Get-CimInstance Win32_Processor | "
             "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,"
             "MaxClockSpeed,CurrentVoltage | Format-List | Out-String"))

    print("=" * 70)
    print("GPU")
    print(ps("Get-CimInstance Win32_VideoController | "
             "Select-Object Name,DriverVersion,CurrentRefreshRate | "
             "Format-List | Out-String"))

    print("=" * 70)
    print("nvidia-smi")
    smi = shutil.which("nvidia-smi")
    if not smi:
        for c in (r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                  r"C:\Windows\System32\nvidia-smi.exe"):
            if Path(c).exists():
                smi = c
                break
    print(f"路径: {smi}")
    if smi:
        print(run([smi, "--query-gpu=name,driver_version,power.limit,"
                         "power.max_limit,clocks.max.graphics,temperature.gpu,"
                         "fan.speed", "--format=csv"]))
        print("--- 是否支持锁定频率/电压（-lgc/-lmc 可用性）---")
        print(run([smi, "--help"]).split("--lock-gpu-clocks")[-1][:300]
              if "--lock-gpu-clocks" in run([smi, "--help"]) else
              "未在帮助中找到 --lock-gpu-clocks")

    print("=" * 70)
    print("超频/硬件访问相关工具与驱动")
    for p in (r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
              r"C:\Program Files\MSI Afterburner\MSIAfterburner.exe",
              r"C:\Program Files (x86)\RivaTuner Statistics Server\RTSS.exe",
              r"C:\Windows\System32\DriverStore\FileRepository\iocbios2.inf_amd64"):
        print(f"  {'有' if Path(p).exists() else '无'}  {p}")

    print("=" * 70)
    print("Intel XTU / AMD Ryzen Master")
    for p in (r"C:\Program Files (x86)\Intel\Intel(R) Extreme Tuning Utility",
              r"C:\Program Files\AMD\RyzenMaster"):
        print(f"  {'有' if Path(p).exists() else '无'}  {p}")

    print("=" * 70)
    print("OS 版本判定")
    txt = ps("(Get-CimInstance Win32_OperatingSystem).Caption")
    print(f"  Caption 含 'Windows 11' ? {'Windows 11' in txt}")
    build = ps("(Get-CimInstance Win32_OperatingSystem).BuildNumber").strip()
    print(f"  Build = {build}  -> {'Win11' if int(build or 0) >= 22000 else 'Win10'}")

    print("=" * 70)
    print("电源方案")
    print(ps("powercfg /list | Out-String"))
    print("--- 是否已存在『卓越性能』方案 ---")
    print(ps("(powercfg /list | Select-String -Pattern '卓越|Ultimate|e9a42b02')."
             "__str__() if (powercfg /list | Select-String -Pattern '卓越|Ultimate|e9a42b02')"
             " else '未找到'"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
