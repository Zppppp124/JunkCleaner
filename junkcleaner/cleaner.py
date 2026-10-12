"""清理引擎：卸载 + 残留清理，所有删除动作可逆（隔离区）。"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from . import core, signatures

# --------------------------------------------------------------------------
# 保护规则
# --------------------------------------------------------------------------
# 设计原则
#   1. 只保护「根本身」，不因其在 C 盘就放弃清理——垃圾软件绝大多数就在 C 盘。
#   2. 厂商保护按「路径段」精确匹配，避免 tencent\qq 误伤 tencent\qqpcmgr。
#   3. 明确的垃圾特征优先级最高，可覆盖厂商保护（如微软电脑管家）。

# 系统根：这些目录本身绝不动（其下子目录仍可清理）
SYSTEM_ROOTS = {
    "c:", "c:\\", r"c:\windows", r"c:\program files", r"c:\program files (x86)",
    r"c:\programdata", r"c:\users", r"c:\$recycle.bin",
    r"c:\windows\system32", r"c:\windows\syswow64", r"c:\windows\winsxs",
    r"c:\windows\system32\drivers", r"c:\windows\assembly",
    r"c:\windows\microsoft.net", r"c:\windows\servicing",
}

# 正常软件厂商：按「路径段」精确相等匹配（不是子串）
NORMAL_VENDOR_SEGMENTS = {
    # 腾讯系正常软件（注意：不含 qqpcmgr —— 那是垃圾软件）
    "qq", "wechat", "weixin", "timi", "tencentdocs", "tencentmeeting",
    "wecom", "wxwork", "qqmusic", "qqlive", "tencentvideo", "qqmail",
    "telegram", "tencentgames", "wegame",
    # 其他正常软件厂商
    "microsoft", "windows", "windowsapps", "nvidia", "adobe", "autodesk",
    "google", "mozilla", "blizzard", "steam", "epic games", "mihoyo",
    "wps office", "sogouinput", "nvidia corporation", "blender foundation",
    "python", "python313", "nodejs", "git", "java", "jdk", "blender",
    "jetbrains", "android", "dotnet", "visual studio", "docker",
    "obs studio", "vlc", "7-zip", "winrar", "notepad++", "everything",
    "figma", "slack", "zoom", "discord", "spotify", "vscode",
    "microsoft office", "libreoffice", "wps",
}

# 明确属于垃圾/流氓软件的路径特征（子串匹配，但取值高度特异）
# 命中即视为可清理，优先于上面的厂商保护
JUNK_MARKERS = {
    # 360
    "360safe", "360se", "360se6", "360chrome", "360browser", "360zip",
    "360drivers", "360softmgr", "360 deepscan", "360deepscan", "360mobile",
    # 2345
    "2345explorer", "2345browser", "2345soft", "2345pic", "2345weather",
    "2345goodzip", "2345\\", "haozip",
    # 腾讯电脑管家（关键：qqpcmgr 必须能清）
    "qqpcmgr", "qmpersonalcenter",
    # 金山 / 猎豹
    "duba", "liebao", "cheetah", "kwss",
    # 驱动 / 硬件工具
    "ludashi", "drivergenius", "drivethelife", "drivermaster", "鲁大师",
    # 下载 / 影音 / 工具
    "thunder network", "thunder\\", "xunlei", "kuai_zip", "kuaizip",
    "flashhelper", "flash center", "storm\\", "baofeng", "birdwallpaper",
    "pptv", "funshion", "kuaijianji",
    # 百度推广组件（注意：不含 baidu netdisk）
    "baidusd", "baiduan", "\\baidu\\baidu",
    # 搜狗推广组件（注意：不含 sogouinput）
    "sogouexplorer", "sogou\\wallpaper", "sogou\\desktop",
    # 微软电脑管家
    "pcmanager", "pc manager", "mspcmanager",
    # 其他
    "quickzip", "小鸟壁纸", "猎豹壁纸", "桌面整理", "护眼宝", "加速球",
    "下载器", "highspeeddownload", "95assistant", "wandoujia",
    "dabaicai", "laomaotao", "ushendu", "gamesbox", "gamebox",
}


def _path_segments(text: str) -> list[str]:
    return [seg for seg in re.split(r"[\\/]+", text) if seg]


def _protection_reason(path: Path) -> str | None:
    """返回保护原因；可清理则返回 None。"""
    text = str(path).lower().rstrip("\\")
    (drive, _, _rest) = text.partition(":")
    roots = {r.rstrip("\\") for r in SYSTEM_ROOTS}
    if text in roots:
        return "系统根本身"
    # 明确垃圾特征优先（可覆盖厂商保护）
    if any(marker in text for marker in JUNK_MARKERS):
        return None
    # Windows 系统目录一律不动
    if text.startswith(r"c:\windows"):
        return "Windows 系统目录"
    # 正常软件厂商：按路径段精确匹配
    segments = _path_segments(text)
    for seg in segments:
        if seg in NORMAL_VENDOR_SEGMENTS:
            return f"正常软件目录（{seg}）"
    return None


def _is_protected(path: Path) -> bool:
    return _protection_reason(path) is not None


def protection_reason(path: Path | str) -> str:
    reason = _protection_reason(Path(path))
    return reason or ""


@dataclass
class CleanAction:
    kind: str          # uninstall / kill / service / task / startup / file / registry
    target: str
    ok: bool
    detail: str = ""
    reversible: bool = True
    quarantine: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CleanReport:
    sig_id: str
    name: str
    actions: list[CleanAction] = field(default_factory=list)
    freed_bytes: int = 0
    start: str = ""
    end: str = ""
    manifest: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for a in self.actions if a.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for a in self.actions if not a.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sig_id": self.sig_id, "name": self.name,
            "actions": [a.to_dict() for a in self.actions],
            "freed_bytes": self.freed_bytes, "start": self.start, "end": self.end,
            "manifest": self.manifest, "ok_count": self.ok_count,
            "fail_count": self.fail_count,
        }


def _kill_processes(processes: list[dict[str, Any]], report: CleanReport,
                    log: Callable[[str], None]) -> None:
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]
    for proc in processes:
        pid = proc.get("pid")
        exe = proc.get("exe") or proc.get("name") or ""
        if not exe:
            continue
        killed = False
        detail = ""
        if psutil and pid:
            try:
                p = psutil.Process(int(pid))
                p.kill()
                p.wait(timeout=5)
                killed = True
            except Exception as exc:  # noqa: BLE001
                detail = str(exc)
        if not killed:
            proc_run = core.run(["taskkill", "/F", "/T", "/IM", Path(exe).name], timeout=20)
            killed = proc_run.returncode == 0
            if not detail:
                detail = f"taskkill rc={proc_run.returncode}"
        report.actions.append(CleanAction("kill", exe, killed, detail, reversible=False))
        log(f"结束进程 {exe}: {'成功' if killed else '失败/' + detail}")


def _stop_services(services: list[dict[str, Any]], report: CleanReport,
                   log: Callable[[str], None]) -> None:
    names = [s.get("name") for s in services if s.get("name")]
    for name in names:
        safe = re.sub(r"[^A-Za-z0-9_.\-]", "", name)
        core.run(["sc", "stop", safe], timeout=30)
        proc = core.run(["sc", "delete", safe], timeout=30)
        ok = proc.returncode == 0
        # 删除注册表服务键（可逆性有限，但服务本身是残留）
        core.run_powershell(
            f"Remove-Item -LiteralPath 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\{safe}' "
            f"-Recurse -Force -ErrorAction SilentlyContinue", timeout=30)
        report.actions.append(CleanAction("service", name, ok,
                                          f"sc delete rc={proc.returncode}", reversible=False))
        log(f"删除服务 {name}: {'成功' if ok else '失败'}")


def _remove_tasks(tasks: list[str], report: CleanReport, log: Callable[[str], None]) -> None:
    for task in tasks:
        if not task:
            continue
        proc = core.run(["schtasks", "/Delete", "/TN", task, "/F"], timeout=30)
        ok = proc.returncode == 0
        report.actions.append(CleanAction("task", task, ok,
                                          f"rc={proc.returncode}", reversible=False))
        log(f"删除计划任务 {task}: {'成功' if ok else '失败'}")


def _remove_startup(items: list[str], report: CleanReport, log: Callable[[str], None]) -> None:
    for item in items:
        name = item.split(" = ", 1)[0].strip()
        if not name:
            continue
        ps = (
            "foreach($k in @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run',"
            "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run',"
            "'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run')){"
            f" Remove-ItemProperty -Path $k -Name {json.dumps(name)} "
            "-Force -ErrorAction SilentlyContinue }")
        proc = core.run_powershell(ps, timeout=30)
        report.actions.append(CleanAction("startup", name, proc.returncode == 0))
        log(f"移除开机自启 {name}")


def _uninstall_entries(entries: list[dict[str, Any]], report: CleanReport,
                       log: Callable[[str], None], timeout: int) -> None:
    """执行卸载。默认走静默模式（自动推断静默参数，失败才回退）。"""
    from . import silent_uninstall as _su
    for entry in entries:
        display = entry.get("display_name") or entry.get("subkey") or ""
        if not (entry.get("uninstall_string") or entry.get("quiet_uninstall")):
            report.actions.append(CleanAction("uninstall", display, False,
                                              "该软件无卸载命令", reversible=False))
            continue
        log(f"静默卸载: {display}")
        res = _su.silent_uninstall(entry, timeout=timeout, log=log)
        detail = (f"{res.kind} / {res.method} rc={res.rc}"
                  if res.ok else (res.error or f"rc={res.rc}"))
        report.actions.append(CleanAction("uninstall", display, res.ok,
                                          detail, reversible=False))
        time.sleep(1.0)


def _split_command(cmd: str) -> str | list[str]:
    """把 UninstallString 拆成 argv；含 && 或 | 时交给 cmd 执行。"""
    stripped = cmd.strip()
    if re.search(r"(&&|\|\||[|<>])", stripped):
        return ["cmd.exe", "/c", stripped]
    if stripped.lower().startswith("msiexec"):
        return stripped
    m = re.match(r'^\s*"([^"]+)"\s*(.*)$', stripped)
    if m:
        exe, rest = m.group(1), m.group(2)
        args = re.findall(r'"[^"]*"|\S+', rest)
        return [exe, *[a.strip('"') for a in args]]
    parts = re.findall(r'"[^"]*"|\S+', stripped)
    return [p.strip('"') for p in parts]


def _quarantine_paths(paths: list[str], report: CleanReport, log: Callable[[str], None],
                      manifest: dict[str, Any]) -> None:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            continue
        reason = _protection_reason(p)
        if reason:
            report.actions.append(CleanAction("file", str(p), False,
                                              f"受保护：{reason}"))
            log(f"跳过受保护路径 {p}（{reason}）")
            continue
        dest = core.quarantine_dir() / stamp / report.sig_id / p.name
        size = core.path_size(p, cap_seconds=8.0) if p.is_dir() else (
            p.stat().st_size if p.exists() else 0)
        ok, err = core.safe_move(p, dest)
        moved = ok and not p.exists()
        report.actions.append(CleanAction("file", str(p), moved, err,
                                          reversible=True,
                                          quarantine=str(dest) if moved else ""))
        if moved:
            report.freed_bytes += size
            manifest["moves"].append({"from": str(p), "to": str(dest), "size": size})
        log(f"隔离残留 {p} -> {dest}: {'成功' if moved else '失败 ' + err}")


def _delete_registry(entries: list[dict[str, Any]], report: CleanReport,
                     log: Callable[[str], None], manifest: dict[str, Any]) -> None:
    for entry in entries:
        subkey = entry.get("subkey")
        hive = entry.get("hive") or "HKLM64"
        if not subkey:
            continue
        constant = core.hive_constant(hive)
        ok = core.delete_registry_key(constant, subkey)
        report.actions.append(CleanAction("registry", subkey, ok, hive, reversible=False))
        if ok:
            manifest["registry"].append({"hive": hive, "subkey": subkey})
        log(f"删除卸载注册表项 {hive}\\{subkey}: {'成功' if ok else '失败'}")


def clean_finding(finding: dict[str, Any],
                  uninstall: bool = True,
                  purge_files: bool = True,
                  timeout: int = 600,
                  log: Callable[[str], None] | None = None) -> CleanReport:
    """清理单个家族。finding 为 scanner.Finding.to_dict() 或同结构 dict。"""
    if log is None:
        def log(_msg: str) -> None:  # noqa: ANN001
            pass
    report = CleanReport(sig_id=finding.get("sig_id", "?"),
                         name=finding.get("name", "?"),
                         start=time.strftime("%Y-%m-%d %H:%M:%S"))
    manifest: dict[str, Any] = {"sig_id": report.sig_id, "name": report.name,
                                "time": report.start, "moves": [], "registry": []}
    log(f"===== 开始清理 {report.name} =====")

    if uninstall:
        _uninstall_entries(list(finding.get("uninstall_entries") or []), report, log, timeout)
        # 卸载后重新扫描一次相关进程/服务（很多卸载器会留下残余）
        processes = _refresh_processes(finding)
        services = list(finding.get("services") or [])
    else:
        processes = list(finding.get("processes") or [])
        services = list(finding.get("services") or [])

    if processes:
        _kill_processes(processes, report, log)
    if services:
        _stop_services(services, report, log)
    if finding.get("tasks"):
        _remove_tasks(list(finding["tasks"]), report, log)
    if finding.get("startup"):
        _remove_startup(list(finding["startup"]), report, log)
    if purge_files:
        _quarantine_paths(list(finding.get("paths") or []), report, log, manifest)
    _delete_registry(list(finding.get("uninstall_entries") or []), report, log, manifest)

    report.end = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        manifest_dir = core.data_dir() / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        mp = manifest_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{report.sig_id}.json"
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        report.manifest = str(mp)
    except OSError:
        pass
    core.log_event("clean", report.to_dict())
    log(f"===== 清理结束 {report.name}: 成功 {report.ok_count} 失败 {report.fail_count} =====")
    return report


def _refresh_processes(finding: dict[str, Any]) -> list[dict[str, Any]]:
    """按签名进程特征重新抓取当前仍存活的进程。"""
    sig = signatures.by_id(finding.get("sig_id", ""))
    if not sig or not sig["process"]:
        return []
    patterns = [re.compile(p, re.I) for p in sig["process"]]
    out = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                info = p.info
                target = info.get("exe") or info.get("name") or ""
                if any(rx.search(target) for rx in patterns):
                    out.append({"pid": info.get("pid"), "name": info.get("name"),
                                "exe": info.get("exe"),
                                "cmdline": " ".join(info.get("cmdline") or [])})
            except Exception:  # noqa: BLE001
                continue
    except ImportError:
        return list(finding.get("processes") or [])
    return out


def clean_many(findings: list[dict[str, Any]], **kwargs: Any) -> list[CleanReport]:
    return [clean_finding(f, **kwargs) for f in findings]


# --------------------------------------------------------------------------
# 隔离区还原
# --------------------------------------------------------------------------
def list_manifests() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mdir = core.data_dir() / "manifests"
    if not mdir.exists():
        return out
    for f in sorted(mdir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["_file"] = str(f)
        data["_moves"] = len(data.get("moves", []))
        data["_size"] = sum(int(m.get("size", 0)) for m in data.get("moves", []))
        out.append(data)
    return out


def restore_manifest(manifest_path: str | Path,
                     log: Callable[[str], None] | None = None) -> list[CleanAction]:
    if log is None:
        def log(_msg: str) -> None:  # noqa: ANN001
            pass
    actions: list[CleanAction] = []
    try:
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [CleanAction("restore", str(manifest_path), False, str(exc))]
    for move in data.get("moves", []):
        src = Path(move.get("to", ""))
        dst = Path(move.get("from", ""))
        if not src.exists():
            actions.append(CleanAction("restore", str(dst), False, "隔离文件不存在"))
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst = dst.with_name(dst.name + "_restored")
            shutil.move(str(src), str(dst))
            actions.append(CleanAction("restore", str(dst), True))
            log(f"还原 {src} -> {dst}")
        except Exception as exc:  # noqa: BLE001
            actions.append(CleanAction("restore", str(dst), False, str(exc)))
    return actions
