"""JunkCleaner 启动器：优先以管理员身份启动 GUI，失败则普通启动。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    target = str(ROOT / "junkcleaner_entry.py")
    if ctypes.windll.shell32.IsUserAnAdmin():
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, target, "--gui"])
        return 0
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable,
            subprocess.list2cmdline([target, "--gui"]), str(ROOT), 1)
        if rc > 32:
            return 0
    except Exception:  # noqa: BLE001
        pass
    subprocess.Popen([sys.executable, target, "--gui"], cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
