"""检查 EXE 的图标与版本资源是否写入成功。"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\dist\JunkCleaner.exe")
    if not exe.exists():
        print(f"找不到 {exe}")
        return 1
    print(f"文件: {exe}")
    print(f"大小: {exe.stat().st_size / (1 << 20):.1f} MB")

    data = exe.read_bytes()
    ascii_text = data.decode("latin-1")

    print("=" * 60)
    checks = {
        "管理员清单 (requireAdministrator)": "requireAdministrator" in ascii_text,
        "图标资源 (PNG 数据)": b"\x89PNG" in data[:4 << 20],
        "ICO 资源目录": b"\x00\x00\x01\x00" in data[:8 << 20],
        "版本: ProductName": "ProductName" in ascii_text
                              or "ProductName".encode("utf-16-le") in data,
        "版本: FileVersion 1.0.0.0": "1.0.0.0" in ascii_text
                                     or "1.0.0.0".encode("utf-16-le") in data,
        "版本: JunkCleaner 净扫": "JunkCleaner".encode("utf-16-le") in data,
    }
    for k, v in checks.items():
        print(f"  [{'OK' if v else '--'}] {k}")

    # 用 Windows API 读取 exe 图标数量
    try:
        import ctypes
        n = ctypes.windll.shell32.ExtractIconExW(str(exe), -1, None, None, 0)
        print(f"  [{'OK' if n else '--'}] 图标组数量: {n}")
    except Exception as exc:  # noqa: BLE001
        print(f"  图标数量读取失败: {exc}")

    # 读取版本资源
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(exe), None)
        print(f"  版本资源大小: {size} 字节")
        if size:
            buf = ctypes.create_string_buffer(size)
            ver.GetFileVersionInfoW(str(exe), 0, size, buf)
            r = ctypes.c_void_p()
            ln = wintypes.UINT()
            for key in ("ProductName", "FileDescription", "FileVersion"):
                if ver.VerQueryValueW(buf, f"\\StringFileInfo\\080404B0\\{key}",
                                      ctypes.byref(r), ctypes.byref(ln)):
                    val = ctypes.wstring_at(r.value, ln.value)
                    print(f"    {key} = {val}")
    except Exception as exc:  # noqa: BLE001
        print(f"  版本读取失败: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
