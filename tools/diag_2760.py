"""查明 2760MHz 这个上限从哪来。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMI = r"C:\Windows\system32\nvidia-smi.EXE"


def run(args: list[str]) -> str:
    p = subprocess.run([SMI, *args], capture_output=True)
    out = (p.stdout or b"") + (p.stderr or b"")
    for e in ("utf-8", "gbk", "cp936"):
        try:
            return out.decode(e)
        except UnicodeDecodeError:
            continue
    return out.decode("utf-8", "replace")


def main() -> int:
    print("=" * 80)
    print("[1] CLOCK 完整信息")
    print(run(["-q", "-d", "CLOCK"])[:3000])

    print("=" * 80)
    print("[2] 应用时钟（applications clocks）")
    print(run(["--query-gpu=clocks.applications.graphics,"
               "clocks.applications.memory,clocks.default.graphics,"
               "clocks.max.graphics,clocks.current.graphics",
               "--format=csv"]))

    print("=" * 80)
    print("[3] 已支持时钟列表（含 P-State）")
    print(run(["-q", "-d", "SUPPORTED_CLOCKS"])[:2500])

    print("=" * 80)
    print("[4] Afterburner 内核驱动是否仍在生效")
    p = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                        "Get-CimInstance Win32_SystemDriver | "
                        "Where-Object {$_.Name -match 'RTCore|RTSS'} | "
                        "Select-Object Name,State,Started | Format-List | Out-String"],
                       capture_output=True)
    print((p.stdout or b"").decode("utf-8", "replace") or "（无）")
    print("相关进程:")
    p2 = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
                         "Get-Process | Where-Object {$_.Name -match "
                         "'Afterburner|RTSS|RivaTuner'} | "
                         "Select-Object Id,Name | Format-Table -AutoSize | Out-String"],
                        capture_output=True)
    print((p2.stdout or b"").decode("utf-8", "replace") or "（无）")

    print("=" * 80)
    print("[5] 尝试把锁去掉（恢复默认）后再看")
    print(run(["--reset-gpu-clocks"]))
    print(run(["--query-gpu=clocks.current.graphics,clocks.gr,clocks.max.gr",
               "--format=csv"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
