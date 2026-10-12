"""用键盘/消息方式切换页签并截图（真实窗口渲染，保证中文字体）。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(r"I:\CODEX\JunkCleaner")
PY = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe"
PYW = r"C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe"


def main() -> int:
    tab = sys.argv[1] if len(sys.argv) > 1 else "6"
    sub_tab = sys.argv[2] if len(sys.argv) > 2 else ""
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else BASE / "tools" / "_shot.png"

    for p in ("JunkCleaner.exe", "pythonw.exe"):
        subprocess.run(["taskkill", "/F", "/IM", p],
                       capture_output=True)
    time.sleep(1)

    env = dict(__import__("os").environ)
    env["JUNKCLEANER_DATA"] = r"C:\ProgramData\JunkCleaner"
    env["JUNKCLEANER_TAB"] = tab
    if sub_tab:
        env["JUNKCLEANER_SUBTAB"] = sub_tab
    proc = subprocess.Popen([PYW, str(BASE / "junkcleaner_entry.py")],
                            cwd=str(BASE), env=env)
    time.sleep(16)

    # 找窗口
    import win32gui
    import win32process
    found: list[int] = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h):
            _, p = win32process.GetWindowThreadProcessId(h)
            if p == proc.pid and win32gui.GetWindowText(h):
                found.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    if not found:
        print("未找到窗口")
        return 1
    hwnd = found[0]
    print(f"hwnd={hwnd} title={win32gui.GetWindowText(hwnd)}")

    time.sleep(3)
    subprocess.run([PY, str(BASE / "tools" / "capture_window.py"),
                    str(proc.pid), str(out)], capture_output=True)
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
