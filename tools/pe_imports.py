"""解析 PE 文件的导入表（不依赖 dumpbin）。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def read_imports(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return []
    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    is_pe32p = magic == 0x20B
    # 数据目录偏移：PE32+ 为 opt+112，PE32 为 opt+96
    dd = opt + (112 if is_pe32p else 96)
    import_rva, _ = struct.unpack_from("<II", data, dd + 8)  # 目录项 1
    if not import_rva:
        return []
    sections = []
    sec = opt + opt_size
    for i in range(num_sections):
        s = sec + i * 40
        va = struct.unpack_from("<I", data, s + 12)[0]
        vsize = struct.unpack_from("<I", data, s + 8)[0]
        raw = struct.unpack_from("<I", data, s + 20)[0]
        sections.append((va, vsize, raw))

    def rva_to_off(rva: int) -> int | None:
        for va, vsize, raw in sections:
            if va <= rva < va + max(vsize, 1):
                return raw + (rva - va)
        return None

    off = rva_to_off(import_rva)
    if off is None:
        return []
    names: list[str] = []
    while True:
        entry = data[off:off + 20]
        if len(entry) < 20:
            break
        name_rva = struct.unpack_from("<I", entry, 12)[0]
        if name_rva == 0:
            break
        n_off = rva_to_off(name_rva)
        if n_off is None:
            break
        end = data.index(b"\0", n_off)
        names.append(data[n_off:end].decode("ascii", "replace"))
        off += 20
    return names


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\d2\minqt2\_internal\PySide6")
    targets = [base / "QtCore.pyd", base / "Qt6Core.dll",
               base / "shiboken6.abi3.dll"]
    for t in targets:
        if not t.exists():
            print(f"{t.name}: 不存在")
            continue
        imps = read_imports(t)
        print(f"=== {t.name} 依赖 {len(imps)} 个模块")
        for n in imps:
            print("   ", n)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
