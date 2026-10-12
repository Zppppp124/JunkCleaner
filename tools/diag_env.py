"""诊断 PATH 污染：查找会把外来 ucrtbase.dll / Qt6Core.dll 带进搜索路径的目录。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BAD_NAMES = ["ucrtbase.dll", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
             "MSVCP140.dll", "VCRUNTIME140.dll", "libcrypto-3-x64.dll"]


def fver(p: Path) -> str:
    try:
        return p.stat().st_size and _fv(p)
    except Exception:  # noqa: BLE001
        return "?"


def _fv(p: Path) -> str:
    import ctypes
    from ctypes import wintypes

    size = ctypes.windll.version.GetFileVersionInfoSizeW(str(p), None)
    if not size:
        return "(no ver)"
    buf = ctypes.create_string_buffer(size)
    if not ctypes.windll.version.GetFileVersionInfoW(str(p), 0, size, buf):
        return "?"
    r = ctypes.c_void_p()
    ln = wintypes.UINT()
    if not ctypes.windll.version.VerQueryValueW(buf, "\\", ctypes.byref(r),
                                                ctypes.byref(ln)):
        return "?"

    class FFI(ctypes.Structure):
        _fields_ = [("sig", wintypes.DWORD), ("struc", wintypes.DWORD),
                    ("ms", wintypes.DWORD), ("ls", wintypes.DWORD)]

    f = ctypes.cast(r, ctypes.POINTER(FFI)).contents
    return f"{f.ms >> 16}.{f.ms & 0xFFFF}.{f.ls >> 16}.{f.ls & 0xFFFF}"


def main() -> int:
    print("系统 ucrtbase:", fver(Path(r"C:\Windows\System32\ucrtbase.dll")))
    print("=" * 78)
    print("在 PATH 上发现的外来同名 DLL：")
    found_any = False
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        d = Path(entry)
        if not d.is_dir():
            continue
        for name in BAD_NAMES:
            f = d / name
            if f.exists():
                # 系统目录自身的跳过
                if str(d).lower().startswith(r"c:\windows"):
                    continue
                print(f"  {name:<22} v{fver(f):<16} {f}")
                found_any = True
    if not found_any:
        print("  （无）")

    print("=" * 78)
    print("PATH 中含 codex-runtimes / libheif 的条目：")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        low = entry.lower()
        if "codex-runtimes" in low or "libheif" in low:
            print("  " + entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
