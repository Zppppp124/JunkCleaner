"""逐层加载 Qt6Core 的依赖，定位缺失符号/模块。"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

IMPORTS_OF_INTEREST = [
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
    "MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll",
    "VCRUNTIME140.dll", "VCRUNTIME140_1.dll",
]


def try_dll(path: Path, extra_dirs: list[Path]) -> str:
    for d in extra_dirs:
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except Exception:  # noqa: BLE001
                pass
    try:
        ctypes.WinDLL(str(path), winmode=0x00000008)
        return "OK"
    except OSError as exc:
        return f"FAIL({exc.winerror}) {exc.strerror}"


def main() -> int:
    internal = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\d2\minqt2\_internal")
    ps = internal / "PySide6"
    shiboken = internal / "shiboken6"
    dirs = [ps, internal, shiboken]
    print(f"internal: {internal}")
    print("=" * 70)

    print("按顺序加载 Qt6Core 的依赖:")
    for name in IMPORTS_OF_INTEREST:
        for base in (ps, internal, shiboken):
            p = base / name
            if p.exists():
                print(f"  {name:<22} {try_dll(p, dirs)}   <- {base.name}")
                break
        else:
            print(f"  {name:<22} (未找到)")

    print("=" * 70)
    print("直接加载 QtCore.pyd 的 pyd 模块:")
    pyd = ps / "QtCore.pyd"
    if pyd.exists():
        print(f"  QtCore.pyd: {try_dll(pyd, dirs)}")
    # 列出 Qt6Core 里引用但目录中缺失的常见名字
    print("=" * 70)
    print("目录里是否有:")
    for n in ("d3d11.dll", "dxgi.dll", "opengl32.dll", "dwmapi.dll",
              "user32.dll", "kernel32.dll"):
        present = (ps / n).exists() or (internal / n).exists()
        print(f"  {n:<16} 打包内={'有' if present else '无（应来自系统）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
