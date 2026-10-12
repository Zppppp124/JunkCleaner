"""后台实时防护：内核事件驱动，毫秒级拦截流氓软件安装与运行。

防护层次
--------
1. 进程启动追踪（WMI ``Win32_ProcessStartTrace``，内核 ETW 事件，毫秒级）：
   新进程一出现立即判定，命中特征则结束进程。
2. 目录变更通知（``ReadDirectoryChangesW``，内核文件系统通知）：下载目录 /
   桌面 / Temp 等位置一有新可执行文件落地就判定，命中则隔离安装包。
3. 兜底轮询（默认 2 秒，仅作为事件源失效后的保险）。

白名单 / 黑名单
--------------
显式拦截名单 > 可信白名单 > 签名与启发式判定。用户信任的软件永不被自动误杀。
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import core, signatures, trust

EXE_SUFFIXES = {".exe", ".msi", ".msp", ".bat", ".cmd", ".ps1", ".scr", ".com"}

WATCH_DIRS = [
    r"%USERPROFILE%\Downloads",
    r"%USERPROFILE%\Desktop",
    r"%USERPROFILE%\Documents\Downloads",
    r"%USERPROFILE%\AppData\Local\Temp",
    r"%LOCALAPPDATA%\Temp",
    r"%LOCALAPPDATA%\Microsoft\Windows\INetCache",
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup",
    r"%ProgramData%",
    r"C:\Users\Public\Downloads",
    r"C:\Users\Public\Desktop",
]

# 安装包文件名关键词：下载站捆绑器的强特征
INSTALLER_NAME_RISK = [
    r"高速下载", r"安全下载", r"极速下载", r"下载器", r"安装器", r"安装管家",
    r"@\d+", r"setup.*\d{8,}", r"install.*\d{8,}", r"_.*\d{8,}\.exe$",
    r"software.*download", r"downloader", r"setup_.*\.exe$", r"万能.*安装",
]

# 明确放行的正常软件（本体可用），但它们拉起的第三方安装照拦不误
KNOWN_NORMAL_PROCESSES = [
    r"^wps\.exe$", r"^wpscloudsvr\.exe$", r"^wpscenter\.exe$", r"^et\.exe$",
    r"^wpp\.exe$", r"^wpsupdate\.exe$", r"^ksomisc\.exe$",
    r"^sogouimebroker\.exe$", r"^sgtool\.exe$", r"^pinyinup\.exe$",
    r"^sogoucloud\.exe$", r"^sgime.*\.exe$",
]

# 明确指向「捆绑/推广」的强特征（任何父进程都拦）
STRONG_BUNDLE_TOKENS = [
    r"softmgr", r"tg\.exe$", r"tgp", r"gamebox", r"游戏盒", r"推广",
    r"捆绑", r"全家桶", r"下载器", r"安装管家", r"极速下载", r"高速下载",
    r"安全下载", r"流氓", r"全家桶",
]
# 通用安装器命名（本身不构成拦截理由，只在「正常软件拉起」时作为信号）
MILD_INSTALLER_TOKENS = [
    r"setup", r"installer", r"install", r"安装",
]
# 会被视为「第三方安装落地区」的路径特征
INSTALLER_ZONE_HINTS = [
    r"\\temp\\", r"\\downloads\\", r"\\下載\\", r"\\下载\\",
    r"\\desktop\\", r"\\inetcache\\", r"\\appdata\\local\\temp",
]

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(path))


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text, re.I) is not None
    except re.error:
        return pattern.lower() in text.lower()


def is_known_normal_exe(name: str) -> bool:
    """判断是否为已知正常软件本体（WPS、搜狗输入法等）。"""
    if not name:
        return False
    return any(_safe_search(p, name) for p in KNOWN_NORMAL_PROCESSES)


class InstallerWatcher:
    """实时防护引擎：WMI 进程追踪 + 目录变更通知，均可降级为轮询。"""

    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 interval: float = 2.0) -> None:
        self.notify = notify
        self.interval = interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._dir_threads: list[threading.Thread] = []
        self._seen_pids: set[int] = set()
        self._seen_files: dict[str, float] = {}
        self._recent_blocks: dict[str, float] = {}
        self._process_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._file_queue: queue.Queue[str] = queue.Queue()
        self.stats = {"blocked": 0, "quarantined": 0, "scanned": 0,
                      "events": 0, "started": "", "mode": "未启动"}

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._seed()
        modes: list[str] = []
        for target, name in ((self._wmi_loop, "wmi"),
                             (self._dir_loop, "dir"),
                             (self._poll_loop, "poll"),
                             (self._consume_events, "proc")):
            t = threading.Thread(target=target, name=f"JunkCleaner-{name}", daemon=True)
            t.start()
            self._threads.append(t)
            modes.append(name)
        self.stats["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.stats["mode"] = "内核事件驱动" if "wmi" in modes else "轮询"
        core.log(f"实时防护已启动（{self.stats['mode']}）", source="guard")
        core.write_status(guard_running=True, guard_started=self.stats["started"],
                          guard_mode=self.stats["mode"])

    def stop(self) -> None:
        self._stop.set()
        self._threads.clear()
        core.log("实时防护已停止", source="guard")
        core.write_status(guard_running=False)

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    def _seed(self) -> None:
        for d in WATCH_DIRS:
            try:
                for f in _expand(d).iterdir():
                    try:
                        self._seen_files[os.path.normcase(str(f))] = f.stat().st_mtime
                    except OSError:
                        continue
            except OSError:
                continue
        try:
            import psutil
            self._seen_pids = set(psutil.pids())
        except ImportError:
            pass

    # ---------------- 事件源 1：WMI 进程启动 ----------------
    def _wmi_loop(self) -> None:
        try:
            import pythoncom
            import wmi
        except ImportError as exc:
            core.log(f"WMI 不可用（{exc}），进程监控降级为轮询", level="WARN", source="guard")
            return
        pythoncom.CoInitialize()
        try:
            client = wmi.WMI()
            watcher = client.Win32_ProcessStartTrace.watch_for()
            while not self._stop.is_set():
                try:
                    event = watcher(timeout_ms=800)
                except Exception:  # noqa: BLE001
                    continue
                if event is None:
                    continue
                self.stats["events"] += 1
                pid = int(getattr(event, "ProcessID", 0) or 0)
                name = str(getattr(event, "ProcessName", "") or "")
                self._process_queue.put({"pid": pid, "name": name})
        finally:
            pythoncom.CoUninitialize()

    # ---------------- 事件源 2：目录变更通知 ----------------
    def _dir_loop(self) -> None:
        try:
            import pywintypes
            import win32con
            import win32event
            import win32file
        except ImportError as exc:
            core.log(f"目录监听不可用（{exc}）", level="WARN", source="guard")
            return
        for d in WATCH_DIRS:
            base = _expand(d)
            if not base.exists() or self._stop.is_set():
                continue
            t = threading.Thread(target=self._watch_one_dir, args=(base,),
                                 name=f"JunkCleaner-dir-{base.name}", daemon=True)
            t.start()
            self._dir_threads.append(t)
        while not self._stop.is_set():
            self._stop.wait(1.0)

    def _watch_one_dir(self, base: Path) -> None:
        import pywintypes
        import win32con
        import win32event
        import win32file

        handle = None
        try:
            handle = win32file.CreateFile(
                str(base), win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE
                | win32con.FILE_SHARE_DELETE,
                None, win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS | win32con.FILE_FLAG_OVERLAPPED, None)
            buf = win32file.AllocateReadBuffer(1 << 16)
            ov = pywintypes.OVERLAPPED()
            ov.hEvent = win32event.CreateEvent(None, True, False, None)
            flags = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME
                     | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE
                     | win32con.FILE_NOTIFY_CHANGE_SIZE)
            win32file.ReadDirectoryChangesW(handle, buf, True, flags, ov, None)
            while not self._stop.is_set():
                rc = win32event.WaitForSingleObject(ov.hEvent, 700)
                if rc != 0:
                    continue
                try:
                    results = win32file.GetOverlappedResult(handle, ov, True)
                except Exception:  # noqa: BLE001
                    results = []
                if not results:
                    results = []
                for _action, rel in results:
                    self._file_queue.put(str(base / rel))
                win32event.ResetEvent(ov.hEvent)
                try:
                    win32file.ReadDirectoryChangesW(handle, buf, True, flags, ov, None)
                except Exception:  # noqa: BLE001
                    break
        except Exception as exc:  # noqa: BLE001
            core.log(f"监听目录失败 {base}: {exc}", level="WARN", source="guard")
        finally:
            try:
                if handle:
                    win32file.CancelIo(handle)
                    win32file.CloseHandle(handle)
            except Exception:  # noqa: BLE001
                pass

    # ---------------- 事件源 3：兜底轮询 ----------------
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_files()
                self._poll_processes()
            except Exception as exc:  # noqa: BLE001
                core.log(f"轮询异常: {exc}", level="ERROR", source="guard")
            self._stop.wait(max(1.0, self.interval))

    def _poll_files(self) -> None:
        for d in WATCH_DIRS:
            base = _expand(d)
            if not base.exists():
                continue
            try:
                entries = list(base.iterdir())
            except OSError:
                continue
            for f in entries:
                try:
                    if not f.is_file() or f.suffix.lower() not in EXE_SUFFIXES:
                        continue
                    mtime = f.stat().st_mtime
                except OSError:
                    continue
                key = os.path.normcase(str(f))
                prev = self._seen_files.get(key)
                self._seen_files[key] = mtime
                if prev is None or abs(prev - mtime) > 0.001:
                    self._process_file(f)

    def _poll_processes(self) -> None:
        try:
            import psutil
        except ImportError:
            return
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid in self._seen_pids:
                    continue
                self._seen_pids.add(pid)
                self._handle_process(proc.info)
            except Exception:  # noqa: BLE001
                continue

    # ---------------- 判定与处置 ----------------
    def _consume_events(self) -> None:
        """由工作线程消费事件队列。"""
        while not self._stop.is_set():
            drained = False
            while True:
                try:
                    evt = self._process_queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                self._handle_process(evt)
            while True:
                try:
                    raw = self._file_queue.get_nowait()
                except queue.Empty:
                    break
                drained = True
                p = Path(raw)
                if p.suffix.lower() in EXE_SUFFIXES:
                    self._process_file(p)
            self._stop.wait(0.05 if drained else 0.2)

    def _handle_process(self, info: dict[str, Any]) -> None:
        pid = int(info.get("pid") or 0)
        name = info.get("name") or ""
        exe = info.get("exe") or ""
        cmd = info.get("cmdline") or ""
        # 事件里通常只有名称，补一次路径查询
        if not exe and pid:
            exe = self._query_exe(pid)
        target = exe or name
        if not target:
            return
        self.stats["scanned"] += 1

        # ---- 1. 显式拦截名单 ----
        if trust.is_blocked(exe_path=target, name=name):
            self._kill(pid, target, "命中用户拦截名单", "user_block")
            return

        # ---- 2. 可信白名单忽略名单 ----
        if sig_ignore := self._match_ignore(exe, name, cmd):
            core.log(f"忽略名单放行 {target}（{sig_ignore}）", source="guard")
            return

        # ---- 3. 用户白名单放行 ----
        # 进程启动时也要查指纹：同一文件被解压/复制到别处，路径变了但内容一致，
        # 必须按 SHA-256 放行，否则会被误杀。
        # 性能：只有配置了「指纹白名单」且文件较大时才计算，避免每个进程都读盘。
        if exe:
            digest = trust.hash_if_needed(exe)
            hit = trust.matches(exe_path=exe, name=name, file_hash=digest)
        else:
            hit = trust.matches(name=name)
        if hit:
            core.log(f"可信软件放行（{hit.get('kind')}）{target}", source="guard")
            return

        # ---- 4. 已知正常软件本体：放行，但记录它拉起了什么 ----
        if is_known_normal_exe(Path(target).name):
            core.log_event("normal_app_run", {"pid": pid, "exe": target,
                                              "note": "已知正常软件本体，放行"})
            return

        # ---- 5. 第三方安装由正常软件拉起 -> 拒绝 ----
        # 必须同时「父进程是正常软件」且「子进程本身像捆绑安装器」才拒绝，
        # 避免误杀 WPS/搜狗自己的正常子进程。
        parent = self._parent_of(pid)
        if parent and is_known_normal_exe(parent["name"]) and (
                self._strong_bundle_like(target, cmd)
                or self._matches_rogue_signature(target, cmd)
                or self._mild_installer_in_zone(target)):
            self._kill(pid, target, f"拦截被 {parent['name']} 拉起的第三方安装", "bundle_child")
            return

        # ---- 6. 文件特征匹配 ----
        cfg = core.load_config()
        for sig in signatures.SIGNATURES:
            if sig["id"] in (cfg.get("disabled_signature_ids") or []):
                continue
            if sig["risk"] == "normal":
                continue
            for pattern in sig["process"]:
                if _safe_search(pattern, Path(target).name) or (
                        signature_in_user_zone(exe) and _safe_search(pattern, cmd)):
                    self._kill(pid, target, f"命中特征：{sig['name']}", sig["id"])
                    return
        # ---- 7. 兜底：名字带强捆绑特征的可执行（任何来源） ----
        if self._strong_bundle_like(target, cmd):
            self._kill(pid, target, "疑似捆绑/推广安装器（命中强特征命名）",
                       "heuristic_parent")

    def _match_ignore(self, exe: str, name: str, cmd: str) -> str:
        """忽略名单：命中则无条件放行（优先级最高，仅次于用户拦截名单）。"""
        cfg = core.load_config()
        for item in cfg.get("guard_ignore_names") or []:
            if item and (item.lower() in (name or "").lower()
                         or item.lower() in (exe or "").lower()
                         or item.lower() in (cmd or "").lower()):
                return f"忽略名单：{item}"
        return ""

    def _strong_bundle_like(self, exe: str, cmd: str) -> bool:
        """名字/命令行带明确捆绑、推广、下载器特征。"""
        text = f"{exe} {cmd}"
        if not text.strip():
            return False
        return any(_safe_search(p, text) for p in STRONG_BUNDLE_TOKENS)

    def _mild_installer_in_zone(self, exe: str) -> bool:
        """通用安装器命名，且位于 Temp/下载/桌面等「安装落地区」。"""
        text = exe or ""
        if not text:
            return False
        in_zone = any(_safe_search(p, text) for p in INSTALLER_ZONE_HINTS)
        mild = any(_safe_search(p, text) for p in MILD_INSTALLER_TOKENS)
        return in_zone and mild

    def _matches_rogue_signature(self, exe: str, cmd: str) -> bool:
        """子进程本身是否命中了流氓软件签名（排除 normal 档）。"""
        cfg = core.load_config()
        name = Path(exe).name if exe else ""
        for sig in signatures.SIGNATURES:
            if sig["risk"] == "normal":
                continue
            if sig["id"] in (cfg.get("disabled_signature_ids") or []):
                continue
            for pattern in sig["process"]:
                if _safe_search(pattern, name) or _safe_search(pattern, cmd):
                    return True
        return False

    def _parent_of(self, pid: int) -> dict[str, str] | None:
        try:
            import psutil
            proc = psutil.Process(pid)
            parent = proc.parent()
            if not parent:
                return None
            return {"pid": str(parent.pid), "name": parent.name() or "",
                    "exe": parent.exe() or ""}
        except Exception:  # noqa: BLE001
            return None

    def _children_of(self, pid: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            import psutil
            for child in psutil.Process(pid).children(recursive=True):
                try:
                    out.append({"pid": child.pid, "name": child.name(),
                                "exe": child.exe() or "",
                                "cmdline": " ".join(child.cmdline())})
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        return out

    def _kill(self, pid: int, target: str, reason: str, sig_id: str) -> None:
        killed = False
        if pid:
            try:
                import psutil
                p = psutil.Process(pid)
                p.kill()
                p.wait(timeout=4)
                killed = True
            except Exception:  # noqa: BLE001
                killed = False
        if not killed:
            proc = core.run(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=20)
            killed = proc.returncode == 0
        if killed:
            self.stats["blocked"] += 1
        core.log_event("block_process", {"pid": pid, "exe": target, "reason": reason,
                                         "sig_id": sig_id, "ok": killed})
        core.log(f"拦截进程 {target}（{reason}）{'成功' if killed else '失败'}", source="guard")
        if killed and self.notify:
            self._notify("已拦截流氓软件运行", f"{Path(target).name}\n原因：{reason}")

    def _process_file(self, path: Path) -> None:
        if not path.exists():
            return
        self.stats["scanned"] += 1
        name = path.name
        if self._match_ignore("", name, str(path)):
            return
        if trust.is_blocked(exe_path=str(path)):
            self._block_file(path, "命中用户拦截名单", "user_block")
            return
        # 已知正常软件本体的安装包一律放行（如 WPS_Setup、搜狗输入法安装包）
        if self._is_normal_installer(name):
            return
        matched = trust.matches(exe_path=str(path), name=name,
                                file_hash=trust.sha256_cached(path, fallback=True))
        if matched:
            core.log(f"可信软件放行 {path}", source="guard")
            return
        hit = self._match_installer(name, str(path))
        if hit is None:
            return
        reason, sig_id = hit
        self._block_file(path, reason, sig_id)

    def _is_normal_installer(self, name: str) -> bool:
        """正常软件的官方安装包，放行不拦。"""
        lowered = name.lower()
        if is_known_normal_exe(name):
            return True
        for token in ("wps", "sogou", "wpsupdate"):
            if token in lowered and any(
                    _safe_search(p, lowered) for p in (r"setup", r"install",
                                                       r"\.exe$")):
                # 但名字里带强捆绑特征的仍然拦，例如 "wps_极速下载器"
                if not self._strong_bundle_like(name, ""):
                    return True
        return False

    def _match_installer(self, name: str, full: str) -> tuple[str, str] | None:
        cfg = core.load_config()
        if trust.matches(exe_path=full, name=name, file_hash=trust.sha256(full)):
            return None
        for sig in signatures.SIGNATURES:
            if sig["id"] in (cfg.get("disabled_signature_ids") or []):
                continue
            if sig["risk"] == "normal":
                continue
            patterns = sig["process"] + sig["uninstall"]
            if patterns and any(_safe_search(p, name) for p in patterns):
                return f"命中特征：{sig['name']}", sig["id"]
        if cfg.get("auto_quarantine_installer", True):
            if any(_safe_search(p, name) for p in INSTALLER_NAME_RISK):
                return "疑似下载站捆绑安装器", "heuristic"
        for custom in cfg.get("custom_block_names") or []:
            if custom and custom.lower() in name.lower():
                return f"自定义拦截：{custom}", "custom"
        return None

    def _block_file(self, path: Path, reason: str, sig_id: str) -> None:
        key = os.path.normcase(str(path))
        now = time.time()
        if now - self._recent_blocks.get(key, 0) < 5:
            return
        self._recent_blocks[key] = now
        dest = core.quarantine_dir() / "installers" / f"{int(now)}_{path.name}"
        ok, detail = False, ""
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
            ok = not path.exists()
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
        if ok:
            self.stats["blocked"] += 1
            self.stats["quarantined"] += 1
        core.log_event("block_installer", {"file": str(path),
                                           "quarantine": str(dest) if ok else "",
                                           "reason": reason, "sig_id": sig_id,
                                           "ok": ok, "detail": detail})
        core.log(f"拦截安装包 {path}（{reason}）{'成功' if ok else '失败 ' + detail}",
                 source="guard")
        if self.notify:
            self._notify("已拦截可疑安装包",
                         f"{path.name}\n原因：{reason}\n已移入隔离区，可随时还原。")

    def _notify(self, title: str, message: str) -> None:
        try:
            self.notify(title, message)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _query_exe(pid: int) -> str:
        try:
            import psutil
            return psutil.Process(pid).exe() or ""
        except Exception:  # noqa: BLE001
            return ""


def signature_in_user_zone(exe: str) -> bool:
    lowered = (exe or "").lower()
    return any(zone in lowered for zone in ("\\downloads\\", "\\temp\\", "\\desktop\\",
                                            "\\inetcache\\", "\\appdata\\local\\temp"))


# --------------------------------------------------------------------------
# 随 Windows 启动（计划任务）
# --------------------------------------------------------------------------
TASK_NAME = "JunkCleaner Guard"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "JunkCleaner"


def _entry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "junkcleaner_entry.py"


def _ps_literal(text: str) -> str:
    """生成 PowerShell 单引号字面量（内部单引号翻倍），避免反斜杠转义问题。"""
    return "'" + str(text).replace("'", "''") + "'"


def install_autostart(entry_py: Path | None = None) -> tuple[bool, str]:
    """注册登录自启：写入当前用户的 Run 键，静默最小化到托盘。

    不再使用计划任务。启动参数带 --tray，主程序启动后直接隐藏到
    右下角托盘，不弹主窗口。这样开机后无感常驻，也不依赖 SYSTEM 账户。
    """
    import sys
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = "--tray"
    else:
        exe = core.python_exe_windowless()
        entry = entry_py or _entry_path()
        args = f'"{entry}" --tray'

    # 先清掉可能遗留的旧计划任务，避免两条自启同时生效
    try:
        remove_autostart()
    except Exception:  # noqa: BLE001
        pass

    cmdline = f'"{exe}" {args}'
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, cmdline)
        core.log(f"注册开机自启成功: {cmdline}", source="guard")
        return True, cmdline
    except OSError as exc:
        core.log(f"注册开机自启失败: {exc}", level="ERROR", source="guard")
        return False, str(exc)


def remove_autostart() -> tuple[bool, str]:
    """移除开机自启：删除 Run 键，并清理旧版遗留的计划任务。"""
    removed = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE)
        removed = True
    except FileNotFoundError:
        removed = True
    except OSError:
        pass
    # 兼容旧版本注册过的计划任务
    try:
        core.run_powershell(
            f"Unregister-ScheduledTask -TaskName {json.dumps(TASK_NAME)} "
            f"-Confirm:$false -ErrorAction SilentlyContinue; 'OK'", timeout=60)
    except Exception:  # noqa: BLE001
        pass
    return removed, ""


def autostart_installed() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return bool(str(value).strip())
    except OSError:
        return False


def autostart_info() -> dict[str, Any]:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return {"State": "已启用", "Command": str(value)}
    except OSError:
        return {}


def start_autostart_task() -> tuple[bool, str]:
    proc = core.run_powershell(
        f"Start-ScheduledTask -TaskName {json.dumps(TASK_NAME)} -ErrorAction Stop; 'OK'",
        timeout=60)
    return b"OK" in (proc.stdout or b""), (proc.stdout or b"").decode("utf-8", "replace")


def spawn_detached_guard() -> bool:
    """以无窗口方式拉起独立守护进程。"""
    import subprocess
    import sys
    exe = core.python_exe_windowless()
    try:
        if getattr(sys, "frozen", False):
            # 打包后：直接运行自身 --guard
            subprocess.Popen([exe, "--guard"], close_fds=True,
                             creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)
            return True
        subprocess.Popen([exe, str(_entry_path()), "--guard"], close_fds=True,
                         creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS)
        return True
    except Exception as exc:  # noqa: BLE001
        core.log(f"拉起守护失败: {exc}", level="ERROR", source="guard")
        return False


def guard_process_running() -> bool:
    """检查是否已有独立守护进程在跑（供 GUI 判断，避免重复启动）。"""
    try:
        import psutil
    except ImportError:
        return bool(core.read_status().get("guard_running"))
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or "")
            name = (p.info.get("name") or "").lower()
            if name.startswith("python") and "--guard" in cmd and "junkcleaner" in cmd.lower():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def guard_process_running() -> bool:
    """检查是否已有独立守护进程在跑（供 GUI 判断）。"""
    try:
        import psutil
    except ImportError:
        return bool(core.read_status().get("guard_running"))
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            name = (p.info.get("name") or "").lower()
            if name.startswith("python") and "--guard" in cmd and "junkcleaner" in cmd.lower():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def stop_external_guards() -> int:
    """结束由计划任务拉起的独立守护进程，返回结束数量。"""
    stopped = 0
    try:
        import psutil
    except ImportError:
        return 0
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info.get("cmdline") or [])
            name = (p.info.get("name") or "").lower()
            if name.startswith("python") and "--guard" in cmd and "junkcleaner" in cmd.lower():
                p.kill()
                stopped += 1
        except Exception:  # noqa: BLE001
            continue
    if stopped:
        core.write_status(guard_running=False)
        core.log(f"已结束 {stopped} 个独立守护进程", source="guard")
    return stopped
