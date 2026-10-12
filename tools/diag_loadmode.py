"""测试不同 DLL 加载模式，定位依赖解析问题。"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

MODE_LABELS = {
    0x00000000: "DEFAULT",
    0x00000008: "LOAD_WITH_ALTERED_SEARCH_PATH",
    0x00001000: "LOAD_LIBRARY_SEARCH_DEFAULT_DIRS",
    0x00000100: "LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR",
    0x00000200: "LOAD_LIBRARY_SEARCH_SYSTEM32",
    0x00000400: "LOAD_LIBRARY_SEARCH_USER_DIRS",
}


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\dist_min\minqt\_internal")
    dll = base / "PySide6" / "Qt6Core.dll"
    print(f"DLL: {dll}  exists={dll.exists()}")
    print("=" * 66)
    for mode, label in MODE_LABELS.items():
        try:
            ctypes.WinDLL(str(dll), winmode=mode)
            print(f"  {label:<32} LOADED OK")
        except OSError as exc:
            print(f"  {label:<32} FAIL {exc.winerror} {exc.strerror}")

    # 显式把依赖目录加入搜索后再试
    print("=" * 66)
    for d in (base / "PySide6", base, base / "shiboken6"):
        if d.exists():
            try:
                os.add_dll_directory(str(d))
                print(f"  add_dll_directory: {d.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  add failed {d}: {exc}")
    try:
        ctypes.WinDLL(str(dll), winmode=0x00000008)
        print("  加目录后 LOADED OK")
    except OSError as exc:
        print(f"  加目录后 FAIL {exc.winerror} {exc.strerror}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
