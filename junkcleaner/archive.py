"""压缩包支持：在不解压整个包的前提下，列出/读取包内单个文件。

支持 zip、7z、rar、tar 系列（tar/gz/bz2/xz）。rar 走 UnRAR.exe
（WinRAR 自带），其余用标准库或 py7zr。
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import core

# 视为可执行/可运行的文件扩展名（拦截重点）
EXECUTABLE_SUFFIXES = {
    ".exe", ".msi", ".msp", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs",
    ".js", ".jar", ".dll", ".sys", ".reg", ".lnk", ".pif", ".cpl", ".ocx",
}

ZIP_EXT = {".zip", ".jar", ".apk", ".whl", ".egg"}
SEVENZIP_EXT = {".7z"}
RAR_EXT = {".rar"}
TAR_EXT = {".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".gz", ".bz2", ".xz"}


@dataclass
class ArchiveEntry:
    name: str
    size: int = 0
    compressed: int = 0
    is_dir: bool = False

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def is_executable(self) -> bool:
        return self.suffix in EXECUTABLE_SUFFIXES


def is_archive(path: str | Path) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in ZIP_EXT | SEVENZIP_EXT | RAR_EXT | TAR_EXT


def _unrar_exe() -> str:
    for candidate in (
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return shutil.which("unrar") or shutil.which("7z") or ""


def list_entries(path: str | Path) -> list[ArchiveEntry]:
    """列出压缩包内所有条目（不解压）。"""
    suffix = Path(path).suffix.lower()
    try:
        if suffix in ZIP_EXT:
            return _list_zip(path)
        if suffix in SEVENZIP_EXT:
            return _list_7z(path)
        if suffix in RAR_EXT:
            return _list_rar(path)
        if suffix in TAR_EXT:
            return _list_tar(path)
    except Exception as exc:  # noqa: BLE001
        core.log(f"读取压缩包失败 {path}: {exc}", level="WARN", source="archive")
    return []


def _list_zip(path: str | Path) -> list[ArchiveEntry]:
    import zipfile
    out: list[ArchiveEntry] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            out.append(ArchiveEntry(info.filename, info.file_size,
                                    info.compress_size, info.is_dir()))
    return out


def _list_7z(path: str | Path) -> list[ArchiveEntry]:
    import py7zr
    out: list[ArchiveEntry] = []
    with py7zr.SevenZipFile(path, "r") as zf:
        for info in zf.list():
            out.append(ArchiveEntry(info.filename,
                                    int(getattr(info, "uncompressed", 0) or 0),
                                    int(getattr(info, "compressed", 0) or 0),
                                    bool(getattr(info, "is_directory", False))))
    return out


def _list_rar(path: str | Path) -> list[ArchiveEntry]:
    exe = _unrar_exe()
    if not exe:
        return []
    if Path(exe).name.lower() == "7z.exe":
        return _list_with_7z(exe, path)
    proc = core.run([exe, "lb", str(path)], timeout=90)
    text = (proc.stdout or b"").decode("utf-8", "replace")
    out: list[ArchiveEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.lower().endswith(".rar"):
            continue
        candidate = Path(line)
        if candidate.suffix.lower() in RAR_EXT and candidate.is_file():
            continue
        out.append(ArchiveEntry(line, 0, 0, line.endswith(("/", "\\"))))
    return out


def _list_with_7z(exe: str, path: str | Path) -> list[ArchiveEntry]:
    proc = core.run([exe, "l", "-slt", str(path)], timeout=90)
    text = (proc.stdout or b"").decode("utf-8", "replace")
    out: list[ArchiveEntry] = []
    cur: dict[str, str] = {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur.get("Path"):
                name = cur["Path"]
                out.append(ArchiveEntry(
                    name,
                    int(cur.get("Size") or 0),
                    int(cur.get("Packed Size") or 0),
                    cur.get("Attributes", "").startswith("D")))
            cur = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            cur[k.strip()] = v.strip()
    return out


def _list_tar(path: str | Path) -> list[ArchiveEntry]:
    import tarfile
    out: list[ArchiveEntry] = []
    with tarfile.open(path, "r:*") as tf:
        for member in tf.getmembers():
            out.append(ArchiveEntry(member.name, member.size, 0, member.isdir()))
    return out


def read_member_hash(path: str | Path, member_name: str) -> str:
    """读取压缩包内单个成员并返回 SHA-256（用于白名单指纹）。"""
    suffix = Path(path).suffix.lower()
    try:
        if suffix in ZIP_EXT:
            import zipfile
            with zipfile.ZipFile(path) as zf:
                with zf.open(member_name) as fh:
                    return _hash_stream(fh)
        if suffix in SEVENZIP_EXT:
            return _extract_and_hash_7z(path, member_name)
        if suffix in RAR_EXT:
            return _extract_and_hash_rar(path, member_name)
        if suffix in TAR_EXT:
            import tarfile
            with tarfile.open(path, "r:*") as tf:
                fh = tf.extractfile(member_name)
                if fh:
                    return _hash_stream(fh)
    except Exception as exc:  # noqa: BLE001
        core.log(f"读取压缩包成员失败 {path}!{member_name}: {exc}",
                 level="WARN", source="archive")
    return ""


def _hash_stream(fh: Any) -> str:
    h = hashlib.sha256()
    while True:
        block = fh.read(1 << 20)
        if not block:
            break
        h.update(block)
    return h.hexdigest()


def _extract_and_hash_rar(path: str | Path, member_name: str) -> str:
    exe = _unrar_exe()
    if not exe:
        return ""
    with tempfile.TemporaryDirectory(prefix="jc_rar_") as tmp:
        if Path(exe).name.lower() == "7z.exe":
            proc = core.run([exe, "e", "-y", f"-o{tmp}", str(path), member_name],
                            timeout=180)
        else:
            proc = core.run([exe, "e", "-y", str(path), member_name, tmp + os.sep],
                            timeout=180)
        target = Path(tmp) / Path(member_name).name
        if target.exists():
            return _hash_file(target)
    return ""


def _extract_and_hash_7z(path: str | Path, member_name: str) -> str:
    import py7zr
    with tempfile.TemporaryDirectory(prefix="jc_7z_") as tmp:
        with py7zr.SevenZipFile(path, "r") as zf:
            zf.extract(path=tmp, targets=[member_name])
        target = Path(tmp) / member_name
        if target.exists():
            return _hash_file(target)
    return ""


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def filter_entries(entries: list[ArchiveEntry], keyword: str = "",
                   executables_only: bool = False) -> list[ArchiveEntry]:
    out: list[ArchiveEntry] = []
    kw = (keyword or "").lower()
    for e in entries:
        if e.is_dir:
            continue
        if executables_only and not e.is_executable:
            continue
        if kw and kw not in e.name.lower():
            continue
        out.append(e)
    return out
