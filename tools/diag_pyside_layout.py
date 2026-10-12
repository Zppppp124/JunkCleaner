"""检查 onedir 打包结果里 PySide6 的布局，并测试不同 PATH 前置能否加载。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CHILD = r"""
import ctypes, os, sys
d = sys.argv[1]
for sub in ('', 'PySide6', 'shiboken6'):
    p = os.path.join(d, sub) if sub else d
    if os.path.isdir(p):
        try: os.add_dll_directory(p)
        except Exception: pass
try:
    from PySide6 import QtCore
    print('QT_IMPORT_OK')
except Exception as e:
    print('QT_IMPORT_FAIL', e)
"""


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\d2\minqt2")
    internal = root / "_internal"
    print(f"root={root}")
    print("=" * 70)
    print("_internal 顶层（前 25）:")
    if internal.exists():
        for i, p in enumerate(sorted(internal.iterdir())):
            if i >= 25:
                break
            print(f"  {'[D]' if p.is_dir() else '   '} {p.name}")
    print("=" * 70)
    ps = internal / "PySide6"
    print(f"PySide6 目录存在: {ps.exists()}")
    if ps.exists():
        names = sorted(p.name for p in ps.iterdir())
        print(f"  文件数: {len(names)}")
        for key in ("QtCore.pyd", "Qt6Core.dll", "__init__.py", "__init__.pyc"):
            print(f"  {key}: {key in names}")

    # 用子进程测试 import，PATH 里加上 PySide6 目录
    env = dict(os.environ)
    env["PATH"] = str(ps) + os.pathsep + str(internal) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run([sys.executable, "-c", CHILD, str(internal)],
                          capture_output=True, env=env)
    print("=" * 70)
    print("子进程 import PySide6.QtCore（把 PySide6 目录加进 PATH）:")
    print("  " + ((proc.stdout or b"") + (proc.stderr or b"")).decode(
        "utf-8", "replace").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
