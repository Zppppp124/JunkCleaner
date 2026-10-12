"""读取 PE 文件的导出表（用于探测 NVAPI 等 DLL 的可用函数）。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path


def _rva_to_off(sections, rva: int) -> int | None:
    for va, vsize, raw in sections:
        if va <= rva < va + max(vsize, 1):
            return raw + (rva - va)
    return None


def read_exports(path: Path) -> list[str]:
    data = path.read_bytes()
    if data[:2] != b"MZ":
        return []
    e = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e:e + 4] != b"PE\0\0":
        return []
    coff = e + 4
    nsec = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    is64 = magic == 0x20B
    dd = opt + (112 if is64 else 96)
    exp_rva, _ = struct.unpack_from("<II", data, dd)          # 目录项 0
    if not exp_rva:
        return []
    sections = []
    sec = opt + opt_size
    for i in range(nsec):
        s = sec + i * 40
        # 0 Name(8), 8 VirtualSize, 12 VirtualAddress,
        # 16 SizeOfRawData, 20 PointerToRawData
        vsize = struct.unpack_from("<I", data, s + 8)[0]
        va = struct.unpack_from("<I", data, s + 12)[0]
        raws = struct.unpack_from("<I", data, s + 16)[0]
        raw = struct.unpack_from("<I", data, s + 20)[0]
        vsize = max(vsize, raws)      # 有些镜像 VirtualSize 为 0
        sections.append((va, vsize, raw))
    off = _rva_to_off(sections, exp_rva)
    if off is None:
        return []
    # IMAGE_EXPORT_DIRECTORY 字段偏移：
    #   0 Characteristics, 4 TimeDateStamp, 8 Major/Minor, 12 Name,
    #   16 Base, 20 NumberOfFunctions, 24 NumberOfNames,
    #   28 AddressOfFunctions, 32 AddressOfNames, 36 AddressOfNameOrdinals
    n_names = struct.unpack_from("<I", data, off + 24)[0]
    names_rva = struct.unpack_from("<I", data, off + 32)[0]
    noff = _rva_to_off(sections, names_rva)
    if noff is None:
        return []
    out: list[str] = []
    for i in range(min(n_names, 20000)):
        n_rva = struct.unpack_from("<I", data, noff + i * 4)[0]
        p = _rva_to_off(sections, n_rva)
        if p is None:
            continue
        end = data.find(b"\0", p)
        if end < 0:
            continue
        out.append(data[p:end].decode("ascii", "replace"))
    return out


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"C:\Windows\System32\nvapi64.dll")
    names = read_exports(target)
    print(f"{target.name}: {len(names)} 个导出")
    for n in names[:60]:
        print("  ", n)
