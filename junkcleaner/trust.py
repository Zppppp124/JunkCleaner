"""可信软件白名单：用户明确信任的软件绕过自动识别与拦截。

白名单优先级高于签名匹配与启发式判定（先看显式拦截名单），可避免误杀。
支持四种信任方式：

path      可执行文件或整个安装目录（前缀匹配，最常用）
hash      单个文件的 SHA-256（最精确）
publisher 文件版本信息里的公司名（宽松，按子串匹配）
name      软件显示名（最宽松，仅供「扫描结果」中手动豁免）

另提供 Windows Defender 排除项管理：把信任目录/文件加入 Defender 排除列表，
避免本工具信任的程序被系统实时保护拦下（会降低系统安全性，界面中明确提示）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from . import core

TRUST_KINDS = {
    "path": "文件/目录路径",
    "hash": "文件指纹 SHA-256",
    "publisher": "发行商",
    "name": "软件名称",
}


def trust_path() -> Path:
    return core.data_dir() / "trust.json"


def block_path() -> Path:
    return core.data_dir() / "blocked.json"


# --------------------------------------------------------------------------
# 显式拦截名单（优先级高于可信白名单）
# --------------------------------------------------------------------------
def load_blocked() -> list[dict[str, Any]]:
    try:
        raw = json.loads(block_path().read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [e for e in raw if isinstance(e, dict) and e.get("value")]
    except (OSError, ValueError):
        pass
    return []


def save_blocked(entries: list[dict[str, Any]]) -> None:
    tmp = block_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(block_path())


def add_blocked(name: str, value: str, note: str = "") -> dict[str, Any]:
    entries = load_blocked()
    for e in entries:
        if e.get("value", "").lower() == value.lower():
            return e
    entry = {"id": uuid.uuid4().hex[:12], "name": name or value, "value": value,
             "note": note, "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    entries.append(entry)
    save_blocked(entries)
    return entry


def remove_blocked(entry_id: str) -> bool:
    entries = load_blocked()
    kept = [e for e in entries if e.get("id") != entry_id]
    if len(kept) == len(entries):
        return False
    save_blocked(kept)
    return True


def is_blocked(name: str | None = None, exe_path: str | None = None) -> bool:
    """显式拦截名单：匹配软件名或路径子串。"""
    name_l = (name or "").lower()
    exe_l = (exe_path or "").lower()
    for e in load_blocked():
        v = str(e.get("value") or "").lower()
        if not v:
            continue
        if v in name_l or (exe_l and v in exe_l):
            return True
    return False


def load_trust() -> list[dict[str, Any]]:
    try:
        raw = json.loads(trust_path().read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [e for e in raw if isinstance(e, dict) and e.get("value")]
    except (OSError, ValueError):
        pass
    return []


def save_trust(entries: list[dict[str, Any]]) -> None:
    tmp = trust_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(trust_path())


def add_trust(name: str, kind: str, value: str, note: str = "",
              source: str = "manual") -> dict[str, Any]:
    entries = load_trust()
    value = value.strip()
    for e in entries:
        if e.get("kind") == kind and e.get("value", "").lower() == value.lower():
            e.update({"name": name or e.get("name", ""), "enabled": True, "note": note})
            save_trust(entries)
            return e
    entry = {
        "id": uuid.uuid4().hex[:12],
        "name": name or value,
        "kind": kind,
        "value": value,
        "note": note,
        "source": source,
        "enabled": True,
        "added": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    entries.append(entry)
    save_trust(entries)
    core.log(f"新增可信项 [{kind}] {name} -> {value}", source="trust")
    return entry


def remove_trust(entry_id: str) -> bool:
    entries = load_trust()
    kept = [e for e in entries if e.get("id") != entry_id]
    if len(kept) == len(entries):
        return False
    save_trust(kept)
    core.log(f"移除可信项 {entry_id}", source="trust")
    return True


def set_enabled(entry_id: str, enabled: bool) -> bool:
    entries = load_trust()
    found = False
    for e in entries:
        if e.get("id") == entry_id:
            e["enabled"] = bool(enabled)
            found = True
    if found:
        save_trust(entries)
    return found


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)).rstrip("\\")


def matches(exe_path: str | None = None, name: str | None = None,
            publisher: str | None = None, file_hash: str | None = None,
            entries: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """返回命中的可信项；未命中返回 None。"""
    entries = entries if entries is not None else load_trust()
    exe_norm = _norm(exe_path) if exe_path else ""
    name_l = (name or "").lower()
    pub_l = (publisher or "").lower()
    for e in entries:
        if not e.get("enabled", True):
            continue
        kind = e.get("kind")
        value = str(e.get("value") or "")
        if kind == "path":
            if not exe_norm:
                continue
            v = _norm(value)
            if exe_norm == v or exe_norm.startswith(v + "\\"):
                return e
        elif kind == "hash":
            if file_hash and file_hash.lower() == value.lower():
                return e
        elif kind == "publisher":
            if pub_l and value.lower() in pub_l:
                return e
        elif kind == "name":
            if name_l and value.lower() in name_l:
                return e
    return None


# --------------------------------------------------------------------------
# 文件信息
# --------------------------------------------------------------------------
_HASH_CACHE: dict[str, tuple[float, int, str]] = {}


def sha256_cached(path: str | Path, limit: int = 512 << 20,
                  fallback: bool = False) -> str:
    """按 (路径, mtime, 大小) 缓存指纹，避免每次进程启动都重算。

    fallback=True 时会计算超过 limit 的大文件（进程判定需要准确指纹）。
    """
    key = str(path)
    try:
        st = os.stat(key)
        mtime, size = st.st_mtime, st.st_size
    except OSError:
        return ""
    cached = _HASH_CACHE.get(key)
    if cached and cached[0] == mtime and cached[1] == size:
        return cached[2]
    value = sha256(path, limit=(2 ** 62) if fallback else limit)
    if value:
        _HASH_CACHE[key] = (mtime, size, value)
    return value


def has_hash_rules() -> bool:
    """是否存在「按指纹」的白名单规则。没有就不必为进程计算指纹。"""
    return any(e.get("kind") == "hash" and e.get("enabled", True)
               for e in load_trust())


def hash_if_needed(path: str | Path, min_size: int = 256 * 1024) -> str:
    """仅在确有指纹规则、且文件不太小时才计算指纹，减少 I/O。

    小于 min_size 的文件即使不全量读取也很快，但为了压低开销，
    统一要求「存在指纹规则」这一前提，绝大多数用户不会有额外读盘。
    """
    if not has_hash_rules():
        return ""
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    if size < min_size:
        return sha256_cached(path)
    return sha256_cached(path, fallback=True)


def sha256(path: str | Path, chunk: int = 1 << 20, limit: int = 512 << 20) -> str:
    """计算 SHA-256；超过 limit 只读前 limit 字节（用于大安装包快速指纹）。"""
    h = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as fh:
            while True:
                if read >= limit:
                    break
                block = fh.read(min(chunk, limit - read))
                if not block:
                    break
                h.update(block)
                read += len(block)
    except OSError:
        return ""
    return h.hexdigest()


def file_info(path: str | Path) -> dict[str, str]:
    """读取版本信息（公司/产品/说明）与签名者（尽力而为）。"""
    info = {"company": "", "product": "", "description": "", "signer": ""}
    try:
        import win32api
        trans = {"CompanyName": "company", "ProductName": "product",
                 "FileDescription": "description"}
        for key, field in trans.items():
            for table in ("\\", r"\VarFileInfo\Translation"):
                try:
                    raw = win32api.GetFileVersionInfo(str(path), table)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(raw, dict):
                    if key in raw:
                        info[field] = str(raw[key]).strip("\x00")
            try:
                lang = win32api.GetFileVersionInfo(str(path), r"\VarFileInfo\Translation")
                if lang:
                    code = f"{lang[0][0]:04x}{lang[0][1]:04x}"
                    value = win32api.GetFileVersionInfo(str(path), f"\\StringFileInfo\\{code}\\{key}")
                    if value:
                        info[field] = str(value).strip("\x00")
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    try:
        proc = core.run_powershell(
            f"(Get-AuthenticodeSignature -LiteralPath {json.dumps(str(path))}).SignerCertificate.Subject",
            timeout=25)
        subject = (proc.stdout or b"").decode("utf-8", "replace").strip()
        m = re.search(r"CN=([^,]+)", subject)
        if m:
            info["signer"] = m.group(1).strip()
    except Exception:  # noqa: BLE001
        pass
    return info


# --------------------------------------------------------------------------
# 已安装软件（供「选择可信软件」列表）
# --------------------------------------------------------------------------
def installed_software(include_system: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in core.iter_uninstall_entries():
        name = (entry.get("display_name") or "").strip()
        if not name:
            continue
        low = name.lower()
        if low in seen:
            continue
        seen.add(low)
        if not include_system:
            if name.startswith("Windows 驱动程序包") or name.startswith("Update for"):
                continue
            if low.startswith("microsoft visual c++") or low.startswith("microsoft .net"):
                continue
        exe = _uninstall_exe(entry)
        trusted = matches(exe_path=exe, name=name,
                          publisher=entry.get("publisher")) is not None
        rows.append({
            "name": name,
            "publisher": entry.get("publisher") or "",
            "version": entry.get("version") or "",
            "location": entry.get("install_location") or _exe_dir(exe),
            "exe": exe,
            "trusted": trusted,
            "subkey": entry.get("subkey") or "",
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def _uninstall_exe(entry: dict[str, Any]) -> str:
    for key in ("quiet_uninstall", "uninstall_string", "icon"):
        raw = (entry.get(key) or "").strip()
        if not raw:
            continue
        m = re.match(r'^\s*"([^"]+\.exe)"', raw, re.I)
        if m:
            return m.group(1)
        m = re.match(r"^\s*([^\s]+\.exe)", raw, re.I)
        if m:
            return m.group(1)
    return ""


def _exe_dir(exe: str) -> str:
    try:
        return str(Path(exe).parent) if exe else ""
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------
# Windows Defender 排除项
# --------------------------------------------------------------------------
def defender_exclusions() -> list[str]:
    proc = core.run_powershell(
        "(Get-MpPreference).ExclusionPath | ConvertTo-Json -Compress", timeout=45)
    text = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, str):
        return [data]
    if isinstance(data, list):
        return [str(x) for x in data]
    return []


def add_defender_exclusion(path: str) -> tuple[bool, str]:
    if not core.is_admin():
        return False, "需要管理员权限"
    proc = core.run_powershell(
        f"Add-MpPreference -ExclusionPath {json.dumps(path)} -ErrorAction Stop; 'OK'",
        timeout=60)
    ok = b"OK" in (proc.stdout or b"")
    detail = (proc.stdout or b"").decode("utf-8", "replace").strip()
    core.log(f"添加 Defender 排除项 {path}: {'成功' if ok else detail}", source="trust")
    return ok, detail


def remove_defender_exclusion(path: str) -> tuple[bool, str]:
    if not core.is_admin():
        return False, "需要管理员权限"
    proc = core.run_powershell(
        f"Remove-MpPreference -ExclusionPath {json.dumps(path)} -ErrorAction Stop; 'OK'",
        timeout=60)
    ok = b"OK" in (proc.stdout or b"")
    return ok, (proc.stdout or b"").decode("utf-8", "replace").strip()
