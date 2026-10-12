"""对比打包前/后的关键运行时 DLL 版本，定位 DLL 冲突。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NAMES = ["MSVCP140.dll", "MSVCP140_1.dll", "MSVCP140_2.dll",
         "VCRUNTIME140.dll", "VCRUNTIME140_1.dll", "ucrtbase.dll",
         "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll"]


def ver(p: Path) -> str:
    if not p.exists():
        return "-"
    try:
        return Path(p).stat().st_size and _fv(p)
    except Exception:  # noqa: BLE001
        return "?"


def _fv(p: Path) -> str:
    import ctypes
    from ctypes import wintypes

    size = ctypes.windll.version.GetFileVersionInfoSizeW(str(p), None)
    if not size:
        return "no-version"
    buf = ctypes.create_string_buffer(size)
    if not ctypes.windll.version.GetFileVersionInfoW(str(p), 0, size, buf):
        return "?"
    r = ctypes.c_void_p()
    ln = wintypes.UINT()
    if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(r),
                                                ctypes.byref(ln)):
        return "?"

    class FixedFileInfo(ctypes.Structure):
        _fields_ = [("dwSignature", wintypes.DWORD),
                    ("dwStrucVersion", wintypes.DWORD),
                    ("dwFileVersionMS", wintypes.DWORD),
                    ("dwFileVersionLS", wintypes.DWORD)]

    ffi = ctypes.cast(r, ctypes.POINTER(FixedFileInfo)).contents
    return (f"{ffi.dwFileVersionMS >> 16}.{ffi.dwFileVersionMS & 0xFFFF}."
            f"{ffi.dwFileVersionLS >> 16}.{ffi.dwFileVersionLS & 0xFFFF}")


def main() -> int:
    import PySide6
    src = Path(PySide6.__file__).parent
    packed = Path(sys.argv[1]) / "_internal" if len(sys.argv) > 1 else None
    sys32 = Path(r"C:\Windows\System32")

    print(f"{'DLL':<22}{'PySide6源':<18}{'系统Sys32':<18}{'打包后':<18}")
    print("-" * 76)
    for n in NAMES:
        a = ver(src / n)
        b = ver(sys32 / n)
        c = "-"
        if packed:
            for candidate in (packed / "PySide6" / n, packed / n,
                              packed / "shiboken6" / n):
                if candidate.exists():
                    c = ver(candidate)
                    break
        print(f"{n:<22}{a:<18}{b:<18}{c:<18}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
