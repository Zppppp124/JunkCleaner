"""确认调优能力边界：nvidia-smi 能做什么、CPU 电压需要什么。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    smi = r"C:\Windows\system32\nvidia-smi.EXE"
    print("=" * 72)
    print("[1] nvidia-smi 支持的可调项（--help 中搜索关键字）")
    helptext = run([smi, "--help"])
    for key in ("--power-limit", "--lock-gpu-clocks", "--lock-memory-clocks",
                "--reset-gpu-clocks", "--fan", "--voltage", "--set",
                "--gpu-reset"):
        print(f"   {'支持' if key in helptext else '不支持'}  {key}")

    print("=" * 72)
    print("[2] 电压相关：能否读取/设置电压")
    q = run([smi, "-q", "-d", "VOLTAGE"])
    print(q[:600] if q.strip() else "<无输出>")

    print("=" * 72)
    print("[3] 支持的时钟列表（前 12 行）")
    sc = run([smi, "-q", "-d", "SUPPORTED_CLOCKS"])
    print("\n".join(sc.splitlines()[:14]))

    print("=" * 72)
    print("[4] 功耗与时钟实时状态")
    print(run([smi, "--query-gpu=clocks.gr,clocks.mem,power.draw,"
                     "power.limit,enforced.power.limit,temperature.gpu,"
                     "fan.speed,utilization.gpu",
                     "--format=csv"]))

    print("=" * 72)
    print("[5] 风扇控制能力")
    print(run([smi, "-q", "-d", "FAN"]))

    print("=" * 72)
    print("[6] CPU 电压调节所需的 MSR 驱动是否已存在")
    drivers = []
    for root in (r"C:\Windows\System32\drivers", r"C:\Windows\SysWOW64\drivers"):
        p = Path(root)
        if p.exists():
            for pat in ("WinRing0*", "inpout*", "ThrottleStop*",
                        "iocbios*", "RTCore*", "NTIOLib*"):
                drivers.extend(p.glob(pat))
    if drivers:
        for d in drivers:
            print(f"   有  {d}")
    else:
        print("   无任何 MSR/OC 驱动（WinRing0 / inpoutx64 / iocbios2 等）")
    try:
        import win32service
        scm = win32service.OpenSCManager(None, None, 0x0004)
        names = []
        for pat in ("WinRing0", "inpout", "iocbios", "RTCore", "ThrottleStop"):
            try:
                for svc in win32service.EnumServicesStatus(scm):
                    if pat.lower() in svc[0].lower():
                        names.append(svc[0])
            except Exception:  # noqa: BLE001
                pass
        print("   已注册的服务:", names or "无")
        win32service.CloseServiceHandle(scm)
    except Exception as exc:  # noqa: BLE001
        print(f"   服务查询失败: {exc}")

    print("=" * 72)
    print("[7] 已有的 CPU 调压工具")
    for p in (r"C:\Program Files\ThrottleStop\ThrottleStop.exe",
              r"C:\Program Files (x86)\ThrottleStop\ThrottleStop.exe",
              r"C:\Program Files (x86)\Intel\Intel(R) Extreme Tuning Utility"
              r"\Intel(R) Extreme Tuning Utility\PerfTune.exe"):
        print(f"   {'有' if Path(p).exists() else '无'}  {p}")

    print("=" * 72)
    print("[8] 卓越性能电源方案测试（只读查询 GUID）")
    print(run(["powercfg", "-list"]))
    print(run(["powercfg", "-query", "e9a42b02-d5df-448d-aa00-03f14749eb61"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
