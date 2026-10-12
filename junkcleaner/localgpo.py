"""本地组策略（Registry.pol）读写。

为什么需要这个
==============
`gpedit.msc` 显示的「已启用 / 未配置」状态，来自本地组策略对象的
    C:\\Windows\\System32\\GroupPolicy\\Machine\\Registry.pol
而不是实时注册表。只把值写进 HKLM\\SOFTWARE\\Policies\\... 能生效，
但 gpedit 仍会显示「未配置」，因为策略文件里没有这条记录。

所以要让 gpedit 正确反映状态、并让策略通过组策略机制稳定下发，
必须写 Registry.pol 并触发一次组策略刷新。

POL 文件格式（MS-GPREG，格式稳定）
==================================
    "PReg" + DWORD 版本(1)
    然后重复：
        '['  key\\0 ;  valueName\\0 ;  type(4B) ;  size(4B) ;  data  ']'
其中 key / valueName 是 UTF-16LE 且自带结尾的 NUL，
分号也是 UTF-16LE（3B 00）。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Iterable

from . import core

POL_MACHINE = Path(r"C:\Windows\System32\GroupPolicy\Machine\Registry.pol")
GPT_INI = Path(r"C:\Windows\System32\GroupPolicy\gpt.ini")

REG_SZ = 1
REG_EXPAND_SZ = 2
REG_BINARY = 3
REG_DWORD = 4
REG_MULTI_SZ = 7


def _enc(text: str) -> bytes:
    """UTF-16LE 编码 + 结尾 NUL（POL 字符串格式）。"""
    return text.encode("utf-16le") + b"\x00\x00"


def _dec(data: bytes) -> str:
    """解码 POL 字符串，去掉结尾 NUL。"""
    if data.endswith(b"\x00\x00"):
        data = data[:-2]
    return data.decode("utf-16le", "replace")


def parse_pol(data: bytes) -> list[dict[str, Any]]:
    """解析 Registry.pol，返回条目列表。"""
    if len(data) < 8 or data[:4] != b"PReg":
        raise ValueError("不是有效的 Registry.pol（缺少 PReg 头）")
    pos = 8
    out: list[dict[str, Any]] = []
    while pos < len(data):
        if data[pos:pos + 2] != b"[\x00":
            break
        pos += 2
        try:
            end = data.index(b";\x00", pos)
        except ValueError:
            break
        key = _dec(data[pos:end])
        pos = end + 2
        try:
            end = data.index(b";\x00", pos)
        except ValueError:
            break
        name = _dec(data[pos:end])
        pos = end + 2
        if pos + 4 > len(data):
            break
        vtype = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if data[pos:pos + 2] != b";\x00":
            break
        pos += 2
        if pos + 4 > len(data):
            break
        size = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if data[pos:pos + 2] != b";\x00":
            break
        pos += 2
        payload = data[pos:pos + size]
        pos += size
        if data[pos:pos + 2] != b"]\x00":
            break
        pos += 2
        out.append({"key": key, "name": name, "type": vtype,
                    "size": size, "data": payload})
    return out


def build_pol(entries: Iterable[dict[str, Any]]) -> bytes:
    """把条目列表序列化成 Registry.pol 字节。"""
    out = bytearray(b"PReg")
    out += struct.pack("<I", 1)
    for e in entries:
        payload = e["data"]
        out += b"[\x00"
        out += _enc(e["key"]) + b";\x00"
        out += _enc(e["name"]) + b";\x00"
        out += struct.pack("<I", int(e["type"])) + b";\x00"
        out += struct.pack("<I", len(payload)) + b";\x00"
        out += payload
        out += b"]\x00"
    return bytes(out)


def read_pol(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or POL_MACHINE
    if not path.exists():
        return []
    return parse_pol(path.read_bytes())


def dword(value: int) -> bytes:
    return struct.pack("<I", int(value) & 0xFFFFFFFF)


def _norm(text: str) -> str:
    return text.rstrip("\x00").lower()


def _same_target(entry: dict[str, Any], key: str, name: str) -> bool:
    return (_norm(entry["key"]) == _norm(key)
            and _norm(entry["name"]) == _norm(name))


def upsert(entries: list[dict[str, Any]], key: str, name: str,
           vtype: int, payload: bytes) -> list[dict[str, Any]]:
    """更新或追加一条策略；保持已有顺序。"""
    for e in entries:
        if _same_target(e, key, name):
            e["type"] = int(vtype)
            e["data"] = payload
            e["size"] = len(payload)
            return entries
    entries.append({"key": key, "name": name, "type": int(vtype),
                    "size": len(payload), "data": payload})
    return entries


def remove(entries: list[dict[str, Any]], key: str,
           name: str) -> list[dict[str, Any]]:
    return [e for e in entries if not _same_target(e, key, name)]


def write_pol(entries: list[dict[str, Any]], path: Path | None = None
              ) -> dict[str, Any]:
    """写回 Registry.pol（先备份原文件）。"""
    path = path or POL_MACHINE
    try:
        if path.exists():
            bak = path.with_suffix(".pol.bak")
            bak.write_bytes(path.read_bytes())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build_pol(entries))
        return {"ok": True, "path": str(path), "entries": len(entries)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def _bump_machine_version() -> bool:
    """把 gpt.ini 的计算机策略版本号 +1，触发重新应用。"""
    if not GPT_INI.exists():
        return False
    try:
        lines = GPT_INI.read_text(encoding="utf-8-sig",
                                  errors="replace").splitlines()
    except OSError:
        return False
    out: list[str] = []
    changed = False
    for line in lines:
        if line.strip().lower().startswith("version="):
            try:
                raw = int(line.split("=", 1)[1].strip() or "0")
            except ValueError:
                raw = 0
            # 高 16 位=用户策略版本，低 16 位=计算机策略版本
            machine = (raw & 0xFFFF) + 1
            user = (raw >> 16) & 0xFFFF
            out.append(f"Version={user << 16 | machine}")
            changed = True
        else:
            out.append(line)
    if not changed:
        return False
    try:
        GPT_INI.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def refresh_policy(timeout: int = 180) -> bool:
    """立即刷新计算机组策略，让改动生效并被 gpedit 识别。"""
    try:
        proc = core.run(["gpupdate", "/force", "/target:computer"],
                        timeout=timeout)
        ok = proc.returncode == 0
        if not ok:
            core.log(f"gpupdate 返回 {proc.returncode}", level="WARN",
                     source="localgpo")
        return ok
    except Exception as exc:  # noqa: BLE001
        core.log(f"gpupdate 执行失败：{exc}", level="WARN", source="localgpo")
        return False


def set_policies(items: list[tuple[str, str, int, bytes]],
                 refresh: bool = True) -> dict[str, Any]:
    """把若干策略写入 Registry.pol。items=[(key, name, type, payload)]。"""
    try:
        entries = read_pol()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"读取 Registry.pol 失败：{exc}"}
    for key, name, vtype, payload in items:
        upsert(entries, key, name, vtype, payload)
    r = write_pol(entries)
    if not r.get("ok"):
        return r
    r["version_bumped"] = _bump_machine_version()
    if refresh:
        refresh_policy()
    core.log(f"已写入本地组策略（共 {r['entries']} 条）", source="localgpo")
    return r


def remove_policies(items: list[tuple[str, str]],
                    refresh: bool = True) -> dict[str, Any]:
    """从 Registry.pol 删除若干策略（回到「未配置」）。"""
    try:
        entries = read_pol()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"读取 Registry.pol 失败：{exc}"}
    before = len(entries)
    for key, name in items:
        entries = remove(entries, key, name)
    r = write_pol(entries)
    if not r.get("ok"):
        return r
    r["removed"] = before - len(entries)
    r["version_bumped"] = _bump_machine_version()
    if refresh:
        refresh_policy()
    core.log(f"已从本地组策略删除 {r['removed']} 条策略", source="localgpo")
    return r


def policy_present(key: str, name: str) -> bool:
    """查询某条策略是否在 Registry.pol 中（即 gpedit 是否显示已配置）。"""
    try:
        for e in read_pol():
            if _same_target(e, key, name):
                return True
    except (OSError, ValueError):
        return False
    return False


def snapshot() -> dict[str, Any]:
    """导出当前策略文件内容（用于备份）。"""
    try:
        entries = read_pol()
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    out = []
    for e in entries:
        value: Any = None
        try:
            if e["type"] == REG_DWORD and len(e["data"]) >= 4:
                value = struct.unpack("<I", e["data"][:4])[0]
            elif e["type"] in (REG_SZ, REG_EXPAND_SZ):
                value = _dec(e["data"])
        except Exception:  # noqa: BLE001
            value = None
        out.append({"key": e["key"].rstrip("\x00"),
                    "name": e["name"].rstrip("\x00"),
                    "type": e["type"], "value": value,
                    "data_hex": e["data"].hex().upper()})
    return {"ok": True, "entries": out}
