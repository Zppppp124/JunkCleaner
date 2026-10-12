"""扫描引擎：把系统里的软件/进程/服务/目录/任务关联到签名库。

判定原则
--------
1. 只有「明确命中签名」才会上榜，绝不凭「发行商」或「目录名前缀」猜测。
2. 每条结果都带证据（命中的注册表项、路径、进程、服务、任务），可人工核对。
3. 争议软件单独标 risk=disputed，默认不勾选。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

from . import core, signatures
from . import trust

RISK_ORDER = {"rogue": 0, "bundle": 1, "disputed": 2, "normal": 3}
RISK_LABEL = {"rogue": "流氓", "bundle": "捆绑", "disputed": "争议", "normal": "正常"}

_COMMON_DIRS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\Users",
    r"%(LOCALAPPDATA)s",
    r"%(APPDATA)s",
    r"%(ProgramData)s",
    r"%(ProgramFiles)s",
    r"%(ProgramFiles(x86)s",
]


def _norm(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def _rx(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.I)
    except re.error:
        return re.compile(re.escape(pattern), re.I)


def _hits(patterns: list[str], *values: str | None) -> list[str]:
    """返回命中的原始值（用于证据展示）。"""
    found: list[str] = []
    for value in values:
        if not value:
            continue
        v = str(value)
        for pat in patterns:
            if _rx(pat).search(v):
                found.append(v)
                break
    return found


@dataclass
class Finding:
    """一个命中的家族及其证据。"""

    sig_id: str
    name: str
    vendor: str
    risk: str
    tags: list[str]
    why: str
    selected: bool
    uninstall_entries: list[dict[str, Any]] = field(default_factory=list)
    processes: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    startup: list[str] = field(default_factory=list)
    computed_size: int = 0
    last_activity: str = ""
    trusted: bool = False
    trusted_by: str = ""
    known_normal: bool = False
    basis: str = ""

    @property
    def evidence_count(self) -> int:
        return (len(self.uninstall_entries) + len(self.processes) + len(self.services)
                + len(self.tasks) + len(self.paths) + len(self.startup))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# 系统信息采集（进程 / 服务 / 计划任务 / 自启 / 已安装目录）
# --------------------------------------------------------------------------
def list_processes(throttle: Any = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        import psutil  # 已随环境提供；无则回退
    except ImportError:
        return _list_processes_ps()
    count = 0
    for p in psutil.process_iter(["pid", "name", "exe", "cmdline", "create_time"]):
        try:
            info = p.info
            out.append({
                "pid": info.get("pid"),
                "name": info.get("name") or "",
                "exe": info.get("exe") or "",
                "cmdline": " ".join(info.get("cmdline") or []),
                "started": info.get("create_time") or 0,
            })
        except Exception:  # noqa: BLE001
            continue
        # 进程枚举会访问每个进程的路径，是 CPU 大户；每个进程都交给节流器
        count += 1
        if throttle is not None:
            throttle.tick()
    return out


def _list_processes_ps() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    proc = core.run_powershell(
        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine "
        "| ConvertTo-Json -Compress", timeout=60)
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    except ValueError:
        return out
    if isinstance(data, dict):
        data = [data]
    for row in data:
        out.append({"pid": row.get("ProcessId"), "name": row.get("Name") or "",
                    "exe": row.get("ExecutablePath") or "",
                    "cmdline": row.get("CommandLine") or "", "started": 0})
    return out


def list_services(throttle: Any = None) -> list[dict[str, Any]]:
    """枚举服务。优先 pywin32（无子进程、低开销），退回 PowerShell。"""
    try:
        import win32service
        out: list[dict[str, Any]] = []
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        try:
            statuses = win32service.EnumServicesStatusEx(
                scm, win32service.SC_ENUM_PROCESS_INFO)
            for idx, (name, display, status) in enumerate(statuses):
                if throttle is not None:
                    throttle.tick()
                try:
                    handle = win32service.OpenService(scm, name, win32service.SERVICE_QUERY_CONFIG)
                    try:
                        cfg = win32service.QueryServiceConfig(handle)
                        path = cfg[3] if len(cfg) > 3 else ""
                    except Exception:  # noqa: BLE001
                        path = ""
                    finally:
                        win32service.CloseServiceHandle(handle)
                except Exception:  # noqa: BLE001
                    path = ""
                state = {1: "Stopped", 2: "StartPending", 3: "StopPending",
                         4: "Running", 5: "ContinuePending", 6: "PausePending",
                         7: "Paused"}.get(status[1], str(status[1]))
                out.append({"name": name, "display": display, "state": state,
                            "start": "", "path": path or ""})
        finally:
            win32service.CloseServiceHandle(scm)
        return out
    except Exception:  # noqa: BLE001
        pass
    proc = core.run_powershell(
        "Get-CimInstance Win32_Service | Select-Object Name,DisplayName,State,StartMode,PathName "
        "| ConvertTo-Json -Compress", timeout=60)
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [{"name": r.get("Name") or "", "display": r.get("DisplayName") or "",
             "state": r.get("State") or "", "start": r.get("StartMode") or "",
             "path": r.get("PathName") or ""} for r in data]


def list_tasks(throttle: Any = None) -> list[dict[str, Any]]:
    """枚举计划任务。用 COM 接口（Task Scheduler），避免启动 PowerShell。"""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        result: list[dict[str, Any]] = []
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            folder = service.GetFolder("\\")
            _walk_tasks(folder, "\\", result, throttle)
        finally:
            # 先释放 COM 引用，再反初始化，避免 IUnknown 释放告警
            folder = None  # type: ignore[assignment]
            service = None  # type: ignore[assignment]
            import gc
            gc.collect()
            pythoncom.CoUninitialize()
        return result
    except Exception:  # noqa: BLE001
        pass
    proc = core.run_powershell(
        "Get-ScheduledTask | Select-Object TaskName,TaskPath,State | ConvertTo-Json -Compress",
        timeout=90)
    try:
        data = json.loads(proc.stdout.decode("utf-8", "replace") or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for r in data:
        out.append({"name": r.get("TaskName") or "",
                    "path": (r.get("TaskPath") or "") + (r.get("TaskName") or ""),
                    "state": r.get("State") or ""})
    return out


def _walk_tasks(node: Any, path: str, out: list[dict[str, Any]],
                throttle: Any = None) -> None:
    """递归收集计划任务（供 list_tasks 复用）。"""
    try:
        tasks = node.GetTasks(1)
    except Exception:  # noqa: BLE001
        tasks = []
    for t in tasks:
        if throttle is not None:
            throttle.tick()
        try:
            out.append({"name": t.Name, "path": f"{path}{t.Name}",
                        "state": str(getattr(t, "State", ""))})
        except Exception:  # noqa: BLE001
            continue
    try:
        subfolders = node.GetFolders(0)
    except Exception:  # noqa: BLE001
        subfolders = []
    for sub in subfolders:
        _walk_tasks(sub, f"{path}{sub.Name}\\", out, throttle)


def list_startup() -> list[dict[str, Any]]:
    """枚举开机自启。直接读注册表（Run 键），不启动任何子进程。"""
    import winreg
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce"),
    ]
    out: list[dict[str, Any]] = []
    for hive, sub in keys:
        try:
            with winreg.OpenKey(hive, sub) as key:
                count = winreg.QueryInfoKey(key)[1]
                for i in range(count):
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    out.append({"name": name, "command": str(value),
                                "key": sub})
        except OSError:
            continue
    return out


def list_install_dirs(roots: list[str] | None = None, max_depth: int = 2) -> list[Path]:
    """枚举常见安装根目录下一到两层的目录名，用于比对安装路径特征。"""
    found: list[Path] = []
    roots = roots or [r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData"]
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        try:
            level1 = list(base.iterdir())
        except OSError:
            continue
        for d1 in level1:
            if not d1.is_dir():
                continue
            found.append(d1)
            if max_depth > 1:
                try:
                    for d2 in d1.iterdir():
                        if d2.is_dir():
                            found.append(d2)
                except OSError:
                    continue
    return found


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def _match_uninstall(entry: dict[str, Any]) -> list[str]:
    """返回命中的签名 id 列表。若命中具体签名，则抑制泛化签名，避免重复。"""
    ids: list[str] = []
    generic_hits: list[str] = []
    for sig in signatures.SIGNATURES:
        if _hits(sig["uninstall"], entry.get("display_name")):
            (generic_hits if sig.get("generic") else ids).append(sig["id"])
    return ids or generic_hits


def scan(progress: Callable[[str, float], None] | None = None,
         include_disputed: bool = True,
         compute_size: bool = True) -> list[Finding]:
    """执行一次全量扫描。progress(stage, ratio)。"""

    def report(stage: str, ratio: float) -> None:
        if progress:
            try:
                progress(stage, ratio)
            except Exception:  # noqa: BLE001
                pass

    findings: dict[str, Finding] = {}
    trust_entries = trust.load_trust()
    blocked_entries = trust.load_blocked()
    intensity = core.scan_intensity()
    throttle = core.Throttle(intensity)
    low_priority = bool(core.load_config().get("low_priority_scan", True))
    if low_priority:
        core.set_low_priority()

    def ensure(sig: dict[str, Any]) -> Finding:
        f = findings.get(sig["id"])
        if f is None:
            f = Finding(
                sig_id=sig["id"], name=sig["name"], vendor=sig["vendor"],
                risk=sig["risk"], tags=list(sig["tags"]), why=sig["why"],
                selected=signatures.default_selected(sig["risk"]),
                basis=sig.get("basis", ""),
            )
            if sig["risk"] == "normal":
                f.trusted = True
                f.trusted_by = "已知正常软件"
                f.known_normal = True
                f.selected = False
            findings[sig["id"]] = f
        return f

    def mark_trust(finding: Finding, exe: str = "", name: str = "",
                   publisher: str = "") -> None:
        # 已知正常软件：显式放行，绝不当垃圾软件处理
        if finding.risk == "normal":
            finding.trusted = True
            finding.trusted_by = "已知正常软件"
            finding.known_normal = True
            finding.selected = False
            return
        # 显式拦截名单优先于可信白名单
        if trust.is_blocked(name=name or finding.name, exe_path=exe):
            finding.trusted = False
            finding.trusted_by = ""
            finding.selected = signatures.default_selected(finding.risk)
            return
        hit = trust.matches(exe_path=exe, name=name or finding.name,
                            publisher=publisher, entries=trust_entries)
        if hit:
            finding.trusted = True
            finding.trusted_by = str(hit.get("name") or hit.get("value") or "")
            finding.selected = False

    report("读取注册表卸载项", 0.05)
    entries = list(core.iter_uninstall_entries())

    report("匹配卸载项", 0.20)
    for entry in entries:
        throttle.tick()
        for sid in _match_uninstall(entry):
            ensure(signatures.by_id(sid))  # type: ignore[arg-type]
            f = findings[sid]
            f.uninstall_entries.append({
                "display_name": entry["display_name"],
                "publisher": entry["publisher"],
                "version": entry["version"],
                "install_location": entry["install_location"],
                "uninstall_string": entry["uninstall_string"],
                "quiet_uninstall": entry["quiet_uninstall"],
                "hive": entry["hive"],
                "subkey": entry["subkey"],
            })
            mark_trust(f, exe=entry.get("install_location") or "",
                       name=entry.get("display_name") or "",
                       publisher=entry.get("publisher") or "")

    report("枚举进程", 0.35)
    processes = list_processes(throttle=throttle)
    report("枚举服务", 0.45)
    services = list_services(throttle=throttle)
    report("枚举计划任务", 0.55)
    tasks = list_tasks(throttle=throttle)
    report("枚举开机自启", 0.62)
    startup = list_startup()

    report("关联进程/服务/任务/自启", 0.70)
    for proc in processes:
        throttle.tick()
        target = proc.get("exe") or proc.get("name") or ""
        for sig in signatures.SIGNATURES:
            if _hits(sig["process"], target, proc.get("name"), proc.get("cmdline")):
                f = ensure(sig)
                f.processes.append({
                    "pid": proc.get("pid"), "name": proc.get("name"),
                    "exe": proc.get("exe"), "cmdline": proc.get("cmdline"),
                })
                mark_trust(f, exe=proc.get("exe") or "")

    for svc in services:
        for sig in signatures.SIGNATURES:
            if _hits(sig["service"], svc.get("name"), svc.get("display"), svc.get("path")):
                ensure(sig).services.append(svc)

    for task in tasks:
        for sig in signatures.SIGNATURES:
            if _hits(sig["task"], task.get("name"), task.get("path")):
                ensure(sig).tasks.append(task.get("path") or task.get("name") or "")

    for item in startup:
        for sig in signatures.SIGNATURES:
            if _hits(sig["task"] + sig["process"], item.get("name"), item.get("command")):
                ensure(sig).startup.append(f"{item.get('name')} = {item.get('command')}")

    report("扫描安装目录", 0.78)
    dirs = list_install_dirs(max_depth=throttle.deep_dirs)
    for d in dirs:
        throttle.tick()
        for sig in signatures.SIGNATURES:
            if _hits(sig["path"], str(d)):
                f = ensure(sig)
                f.paths.append(str(d))
                mark_trust(f, exe=str(d))

    # 去重
    for f in findings.values():
        f.paths = sorted(set(f.paths), key=len)
        f.tasks = sorted(set(f.tasks))
        f.startup = sorted(set(f.startup))

    if compute_size:
        report("估算占用体积", 0.85)
        for f in findings.values():
            throttle.tick()
            total = 0
            for d in f.paths[:4]:
                total += core.path_size(
                    Path(d), cap_seconds=throttle.size_timeout,
                    on_read=throttle.tick, budget=throttle.read_budget)
            f.computed_size = total

    report("整理结果", 0.95)
    result = list(findings.values())
    result.sort(key=lambda f: (RISK_ORDER.get(f.risk, 9), -f.evidence_count, f.name))
    if not include_disputed:
        result = [f for f in result if f.risk != "disputed"]
    report("完成", 1.0)
    core.log(f"扫描完成，命中 {len(result)} 个家族", source="scan")
    if low_priority:
        core.restore_priority()
    try:
        snapshot = {"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(result),
                    "findings": [f.to_dict() for f in result]}
        (core.data_dir() / "last_scan.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        core.update_config(last_scan=snapshot["time"])
    except OSError:
        pass
    return result


def load_last_scan() -> list[dict[str, Any]]:
    try:
        data = json.loads((core.data_dir() / "last_scan.json").read_text(encoding="utf-8"))
        return list(data.get("findings", []))
    except (OSError, ValueError):
        return []


def process_snapshot() -> list[dict[str, Any]]:
    """轻量快照，供后台守护高频调用。"""
    return list_processes()
