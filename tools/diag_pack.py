"""诊断打包后的 Qt DLL 加载问题。"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path


def try_load(base: Path, name: str) -> str:
    p = base / "PySide6" / name
    if not p.exists():
        return f"{name}: 文件不存在"
    try:
        ctypes.CDLL(str(p))
        return f"{name}: LOADED OK"
    except OSError as exc:
        return f"{name}: FAIL -> {exc}"


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\dist_min\minqt")
    internal = target / "_internal"
    print(f"检查目录: {target}")
    print("=" * 60)

    # 列出可疑的运行时 DLL
    for pattern in ("ucrtbase.dll", "VCRUNTIME140.dll", "MSVCP140.dll",
                    "python3*.dll", "shiboken6.abi3.dll"):
        for f in internal.rglob(pattern):
            print(f"  {f.relative_to(internal)}")

    print("=" * 60)
    for d in (internal, internal / "PySide6", internal / "shiboken6"):
        if d.exists():
            try:
                os.add_dll_directory(str(d))
            except Exception:  # noqa: BLE001
                pass

    print("加载测试（当前状态）:")
    for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"):
        print("  " + try_load(internal, name))

    # 备份并移除 ucrtbase.dll 再测
    uc = internal / "ucrtbase.dll"
    if uc.exists():
        bak = internal / "ucrtbase.dll.bak"
        print("\n检测到 _internal\\ucrtbase.dll —— 这是典型的 DLL 冲突源")
        if bak.exists():
            bak.unlink()
        shutil.move(str(uc), str(bak))
        print("已临时重命名为 ucrtbase.dll.bak")
        print("\n加载测试（移除 ucrtbase 后）:")
        for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"):
            print("  " + try_load(internal, name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
