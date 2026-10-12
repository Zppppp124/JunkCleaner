"""测试 Afterburner 的命令行接口能力。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

AB = Path(r"D:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe")


def run(args: list[str], timeout: int = 30) -> tuple[int, str]:
    p = subprocess.run([str(AB), *args], capture_output=True, timeout=timeout,
                       cwd=str(AB.parent))
    out = ((p.stdout or b"") + (p.stderr or b"")).decode("gbk", "replace")
    return p.returncode, out.strip()


def main() -> int:
    print(f"Afterburner: {AB}")
    print(f"存在: {AB.exists()}")
    print("=" * 70)

    # 1) 进程运行状态
    import psutil
    running = [p.info for p in psutil.process_iter(["pid", "name", "exe"])
               if (p.info.get("name") or "").lower() == "msiafterburner.exe"]
    print(f"进程运行中: {bool(running)}  {running}")

    print("=" * 70)
    print("[1] 测试 -Profile 1（应用配置文件）")
    print(f"  rc/out: {run(['-Profile', '1'])}")
    time.sleep(2)

    print("=" * 70)
    print("[2] 测试 -Profile2（第二套配置，对应 Profile2.cfg）")
    print(f"  rc/out: {run(['-Profile2', '1'])}")
    time.sleep(1)

    print("=" * 70)
    print("[3] 测试配置文件路径是否可写")
    prof = Path(r"D:\Program Files (x86)\MSI Afterburner\Profiles"
                r"\VEN_10DE&DEV_2689&SUBSYS_18D410DE&REV_A1&BUS_1&DEV_0&FN_0.cfg")
    try:
        data = prof.read_bytes()
        prof.write_bytes(data)
        print(f"  可写: 是（{len(data)} 字节）")
    except Exception as exc:  # noqa: BLE001
        print(f"  可写: 否 -> {exc}")

    print("=" * 70)
    print("[4] 检查 Afterburner 是否监听配置文件变化")
    before = prof.stat().st_mtime
    print(f"  当前 mtime: {before}")

    print("=" * 70)
    print("[5] 可用的命令行开关（读取 cfg 里的命令行帮助）")
    cfg = Path(r"D:\Program Files (x86)\MSI Afterburner\MSIAfterburner.cfg")
    text = cfg.read_text(encoding="utf-8", errors="replace")
    for key in ("StartupProfile", "StartMinimized", "Profile", "LowLevelIO",
                "UnlockVoltageControl", "UnlockVoltageMonitoring",
                "EnableLowLevelIO"):
        for line in text.splitlines():
            if line.strip().startswith(key + "="):
                print(f"  {line.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
