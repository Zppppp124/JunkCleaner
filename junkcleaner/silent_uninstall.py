"""静默卸载引擎。

设计要点
--------
不同软件的卸载器接受的静默开关不一样，本模块按「卸载器类型」自动选择：

| 类型 | 判定依据 | 静默参数 |
|------|---------|---------|
| MSI | UninstallString 含 msiexec / .msi | /qn /norestart REBOOT=ReallySuppress |
| NSIS | 通常是 Uninstall.exe，支持 /S | /S |
| Inno Setup | 文件名常见 unins000.exe | /VERYSILENT /SUPPRESSMSGBOXES /NORESTART |
| InstallShield | 多为 setup.exe -remove | /s /f1"answer.iss" |
| 通用 | 兜底 | 依次尝试 /S /silent /quiet /qn /VERYSILENT |

策略：
  1. 如果有 QuietUninstallString，直接用（最可靠）
  2. 否则按类型给出候选参数列表，**逐个尝试**，用「进程是否正常结束 +
    卸载项是否消失」判断是否成功
  3. 全部失败则退回普通（可见）卸载，并如实告知用户需要点几下

不静默等待太久：每个候选有超时（默认 10 分钟），超时即认为该软件需要交互。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from . import core

# 常见卸载器的静默参数
CANDIDATES: dict[str, list[list[str]]] = {
    "msi": [
        ["/qn", "/norestart", "REBOOT=ReallySuppress"],
        ["/quiet", "/norestart"],
    ],
    "nsis": [["/S"], ["/S", "/NORESTART"]],
    "inno": [
        ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        ["/SILENT", "/NORESTART"],
    ],
    "installshield": [["/s"], ["/s", "/f1"]],
    "generic": [
        ["/S"], ["/s"], ["/silent"], ["/quiet"], ["/qn"],
        ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
        ["/uninstall", "/S"], ["--silent"],
    ],
}


def classify(uninstall_string: str, quiet: str = "") -> str:
    """判断卸载器类型。"""
    s = (quiet or uninstall_string or "").strip()
    low = s.lower()
    if "msiexec" in low or re.search(r"\.msi(\s|$|\")", low):
        return "msi"
    # 取可执行文件路径（注意命令里可能有额外参数）
    name = ""
    m = re.match(r'^\s*"([^"]+)"', s) or re.match(r"^\s*(\S+)", s)
    if m:
        name = Path(m.group(1)).name.lower()
    # Inno Setup 的卸载器固定叫 unins000.exe / unins001.exe
    if re.match(r"unins\d+\.exe$", name):
        return "inno"
    # InstallShield：带 -remove / /remove 之类的参数
    if re.search(r"[-/]remove\b", low):
        return "installshield"
    if "nsis" in low:
        return "nsis"
    # NSIS 卸载器常见命名
    if re.search(r"(uninst|uninstall|卸载)", name) or "uninst" in name:
        return "generic"
    return "generic"


def _has_silent_arg(argv: list[str]) -> bool:
    """命令里是否已经带了静默参数，避免重复追加。"""
    silent = {"/s", "/silent", "/quiet", "/qn", "/verysilent", "/suppressmsgboxes",
              "--silent", "-s", "/q"}
    return any(a.strip().lower() in silent for a in argv[1:])


@dataclass
class SilentResult:
    display_name: str = ""
    kind: str = ""
    ok: bool = False
    used_args: list[str] = field(default_factory=list)
    method: str = ""            # quiet_string / silent_args / visible / internal
    rc: int | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split(cmd: str) -> list[str]:
    """把卸载命令拆成 argv。"""
    cmd = (cmd or "").strip()
    if not cmd:
        return []
    if re.search(r"(&&|\|\||[|<>])", cmd):
        return ["cmd.exe", "/c", cmd]
    out: list[str] = []
    for tok in re.findall(r'"[^"]*"|\S+', cmd):
        out.append(tok.strip('"'))
    return out


def _entry_still_exists(entry: dict[str, Any]) -> bool:
    """检查卸载注册表项是否还存在。"""
    import winreg
    sub = entry.get("subkey")
    hive = core.hive_constant(entry.get("hive") or "HKLM64")
    if not sub:
        return False
    try:
        with winreg.OpenKey(hive, sub):
            return True
    except OSError:
        return False


def silent_uninstall(entry: dict[str, Any], timeout: int = 600,
                     log: Callable[[str], None] | None = None,
                     verify: bool = True) -> SilentResult:
    """对单个卸载项执行静默卸载。"""
    log = log or (lambda _m: None)
    res = SilentResult(display_name=entry.get("display_name", ""))
    start = time.time()

    quiet = (entry.get("quiet_uninstall") or "").strip()
    normal = (entry.get("uninstall_string") or "").strip()
    if not quiet and not normal:
        res.error = "没有卸载命令"
        return res

    # 1) 优先用软件自带的静默卸载命令
    if quiet:
        res.kind = classify(quiet, quiet)
        log(f"[{res.display_name}] 使用自带的静默卸载命令")
        argv = _split(quiet)
        rc = _run(argv, timeout, log, res)
        res.method = "quiet_string"
        res.used_args = argv
        res.rc = rc
        if _ok(rc, entry, res, verify):
            res.ok = True
            res.seconds = round(time.time() - start, 1)
            return res
        log(f"[{res.display_name}] 自带静默命令未成功，尝试推断参数")

    # 2) 按类型尝试候选参数
    kind = classify(normal, quiet)
    res.kind = kind
    base = _split(normal)
    if not base:
        res.error = "卸载命令无法解析"
        return res

    for args in CANDIDATES.get(kind, CANDIDATES["generic"]):
        if time.time() - start > timeout:
            res.error = "超时"
            break
        # 命令本身已含静默参数就不重复追加
        if _has_silent_arg(base):
            log(f"[{res.display_name}] 卸载命令自带静默参数，直接执行")
            rc = _run(base, timeout - int(time.time() - start), log, res)
            res.attempts.append({"args": ["(已有)"], "rc": rc})
            res.used_args = base
            res.rc = rc
            res.method = "silent_args"
            if _ok(rc, entry, res, verify):
                res.ok = True
            break
        log(f"[{res.display_name}] 尝试静默参数 {' '.join(args)}")
        rc = _run(base + args, timeout - int(time.time() - start), log, res)
        res.attempts.append({"args": args, "rc": rc})
        res.used_args = base + args
        res.rc = rc
        res.method = "silent_args"
        if _ok(rc, entry, res, verify):
            res.ok = True
            break
        time.sleep(1.0)

    if not res.ok and not res.error:
        res.error = "所有静默参数都未能完成卸载（该软件可能需要人工交互）"
    res.seconds = round(time.time() - start, 1)
    core.log(f"静默卸载 {res.display_name}: {'成功' if res.ok else res.error}",
             source="uninstall")
    return res


def _run(argv: list[str], timeout: int, log: Callable[[str], None],
         res: SilentResult) -> int:
    if not argv:
        return -1
    try:
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000   # 不弹黑窗
        p = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **kwargs)
        try:
            return p.wait(timeout=max(30, timeout))
        except subprocess.TimeoutExpired:
            log(f"  超时，结束进程 {argv[0]}")
            p.terminate()
            time.sleep(2)
            if p.poll() is None:
                p.kill()
            return 124
    except FileNotFoundError:
        log(f"  找不到卸载程序: {argv[0]}")
        return 2
    except Exception as exc:  # noqa: BLE001
        log(f"  执行失败: {exc}")
        res.error = str(exc)
        return 3


def _ok(rc: int, entry: dict[str, Any], res: SilentResult,
        verify: bool) -> bool:
    """判断是否卸载成功：返回码 + 注册表项是否消失。"""
    if rc not in (0, 3010, 1641, None):
        # 非 0 不一定是失败（有些卸载器返回 1），继续用注册表验证
        pass
    if not verify:
        return rc in (0, 3010, 1641)
    gone = not _entry_still_exists(entry)
    if gone:
        return True
    # 注册表还在，但返回码成功：可能是延迟清理，再等一会
    if rc in (0, 3010, 1641):
        for _ in range(6):
            time.sleep(2)
            if not _entry_still_exists(entry):
                return True
    return False


def silent_uninstall_many(entries: list[dict[str, Any]], timeout: int = 600,
                          log: Callable[[str], None] | None = None
                          ) -> list[SilentResult]:
    out: list[SilentResult] = []
    for i, e in enumerate(entries, 1):
        if log:
            log(f"=== ({i}/{len(entries)}) {e.get('display_name','')} ===")
        out.append(silent_uninstall(e, timeout=timeout, log=log))
    return out
