"""内存检测与释放。

释放逻辑参考知名内存优化工具（Mem Reduct、RAMMap、Wise Memory Optimizer、
Process Lasso）的公开做法，逐层从「温和」到「强力」：

1. trim_working_sets  逐进程 EmptyWorkingSet，把不活跃页面移出工作集
2. purge_standby_list 清空待机列表（缓存页）—— 释放量最大的一步
3. flush_modified_pages 刷新已修改页面到磁盘
4. set_system_file_cache 降低文件系统缓存上限
5. combine_memory_lists 合并内存列表

待机列表/已修改列表的清理依赖未公开的 NtSetSystemInformation
（SystemMemoryListInformation = 0x50），需要管理员权限。
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field, asdict
from typing import Any

from . import core

# --------------------------------------------------------------------------
# 结构体与常量
# --------------------------------------------------------------------------


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_INFORMATION = 0x0400

SYSTEM_MEMORY_LIST_INFORMATION = 0x50
MemoryPurgeStandbyList = 4
MemoryFlushModifiedList = 3
MemoryEmptyWorkingSets = 2
MemoryCombineInformation = 5

SYSTEM_FILE_CACHE_INFORMATION = 0x15

SE_PROFILE_SINGLE_PROCESS_PRIVILEGE = "SeProfileSingleProcessPrivilege"
SE_INCREASE_QUOTA_PRIVILEGE = "SeIncreaseQuotaPrivilege"

kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
ntdll = getattr(ctypes.windll, "ntdll", None)
advapi32 = ctypes.windll.advapi32


@dataclass
class MemoryStatus:
    total: int = 0
    available: int = 0
    used: int = 0
    percent: float = 0.0
    total_pagefile: int = 0
    avail_pagefile: int = 0
    cached: int = 0
    commit_total: int = 0
    commit_limit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReleaseResult:
    before: MemoryStatus = field(default_factory=MemoryStatus)
    after: MemoryStatus = field(default_factory=MemoryStatus)
    steps: list[dict[str, Any]] = field(default_factory=list)
    trimmed: int = 0
    seconds: float = 0.0

    @property
    def freed(self) -> int:
        return max(0, self.after.available - self.before.available)

    def to_dict(self) -> dict[str, Any]:
        return {"before": self.before.to_dict(), "after": self.after.to_dict(),
                "steps": self.steps, "trimmed": self.trimmed,
                "seconds": self.seconds, "freed": self.freed}


# --------------------------------------------------------------------------
# 状态读取
# --------------------------------------------------------------------------
def status() -> MemoryStatus:
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ok = kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    if not ok:
        return MemoryStatus()
    total = int(st.ullTotalPhys)
    avail = int(st.ullAvailPhys)
    used = total - avail
    result = MemoryStatus(
        total=total, available=avail, used=used,
        percent=(used / total * 100.0) if total else 0.0,
        total_pagefile=int(st.ullTotalPageFile),
        avail_pagefile=int(st.ullAvailPageFile),
    )
    # 任务管理器口径的缓存/已提交来自性能计数器
    try:
        cached, commit_total, commit_limit = _performance_memory()
        result.cached = cached
        result.commit_total = commit_total
        result.commit_limit = commit_limit
    except Exception:  # noqa: BLE001
        pass
    return result


class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", wintypes.DWORD),
        ("ProcessCount", wintypes.DWORD),
        ("ThreadCount", wintypes.DWORD),
    ]


def performance_info() -> dict[str, int]:
    """通过 GetPerformanceInfo 读取系统缓存 / 已提交 / 提交上限（字节）。"""
    info = PERFORMANCE_INFORMATION()
    info.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
    if not psapi.GetPerformanceInfo(ctypes.byref(info), info.cb):
        return {}
    page = int(info.PageSize) or 4096
    return {
        "cached": int(info.SystemCache) * page,
        "commit_total": int(info.CommitTotal) * page,
        "commit_limit": int(info.CommitLimit) * page,
        "physical_total": int(info.PhysicalTotal) * page,
        "physical_available": int(info.PhysicalAvailable) * page,
        "processes": int(info.ProcessCount),
        "threads": int(info.ThreadCount),
        "handles": int(info.HandleCount),
    }


def _performance_memory() -> tuple[int, int, int]:
    """兼容旧调用：返回（缓存字节、已提交、提交上限）。"""
    data = performance_info()
    return (data.get("cached", 0), data.get("commit_total", 0),
            data.get("commit_limit", 0))


# --------------------------------------------------------------------------
# 权限
# --------------------------------------------------------------------------
def _enable_privilege(name: str) -> bool:
    try:
        import win32api
        import win32con
        import win32security
        htoken = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY)
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(
            htoken, False, [(luid, win32con.SE_PRIVILEGE_ENABLED)])
        return win32api.GetLastError() == 0
    except Exception:  # noqa: BLE001
        return False


def enable_all_privileges() -> dict[str, bool]:
    return {
        SE_PROFILE_SINGLE_PROCESS_PRIVILEGE:
            _enable_privilege(SE_PROFILE_SINGLE_PROCESS_PRIVILEGE),
        SE_INCREASE_QUOTA_PRIVILEGE:
            _enable_privilege(SE_INCREASE_QUOTA_PRIVILEGE),
    }


# --------------------------------------------------------------------------
# 释放步骤
# --------------------------------------------------------------------------
def _nt_system_memory(command: int) -> bool:
    """调用 NtSetSystemInformation(SystemMemoryListInformation)。"""
    if ntdll is None:
        return False
    value = ctypes.c_int(command)
    size = ctypes.sizeof(value)
    hproc = kernel32.GetCurrentProcess()
    status = ntdll.NtSetSystemInformation(
        SYSTEM_MEMORY_LIST_INFORMATION, ctypes.byref(value), size)
    return status == 0


def purge_standby_list() -> bool:
    """清空待机列表（缓存页），释放量最大的一步。"""
    return _nt_system_memory(MemoryPurgeStandbyList)


def flush_modified_pages() -> bool:
    """把已修改页面写回磁盘。"""
    return _nt_system_memory(MemoryFlushModifiedList)


def empty_all_working_sets() -> bool:
    return _nt_system_memory(MemoryEmptyWorkingSets)


def combine_memory_lists() -> bool:
    return _nt_system_memory(MemoryCombineInformation)


def trim_working_sets(exclude_self: bool = True,
                      min_size: int = 30 << 20,
                      progress: Any = None) -> int:
    """逐进程修剪工作集。返回成功修剪的进程数。"""
    count = 0
    try:
        import psutil
    except ImportError:
        return 0
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.info["pid"]
            if exclude_self and pid == me:
                continue
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
            if not handle:
                continue
            try:
                if psapi.EmptyWorkingSet(handle):
                    count += 1
            finally:
                kernel32.CloseHandle(handle)
            if progress:
                try:
                    progress(proc.info.get("name") or str(pid))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            continue
    return count


def set_file_cache_limit(max_bytes: int | None = None) -> bool:
    """设置系统文件缓存上限（默认按物理内存 1/8）。"""
    try:
        total = status().total or (8 << 30)
        limit = max_bytes or int(total * 0.125)
        return _nt_system_information(SYSTEM_FILE_CACHE_INFORMATION,
                                      ctypes.c_size_t(limit))
    except Exception:  # noqa: BLE001
        return False


def _nt_system_information(info_class: int, value: Any) -> bool:
    if ntdll is None:
        return False
    status = ntdll.NtSetSystemInformation(
        info_class, ctypes.byref(value), ctypes.sizeof(value))
    return status == 0


# --------------------------------------------------------------------------
# 组合：一键释放
# --------------------------------------------------------------------------
def release(level: str = "standard", progress: Any = None) -> ReleaseResult:
    """执行内存释放。

    level: gentle（仅修剪工作集）/ standard（+待机列表）/ deep（+全部）
    """
    start = time.time()
    result = ReleaseResult(before=status())
    if not core.is_admin():
        result.steps.append({"name": "权限检查", "ok": False,
                             "detail": "需要管理员权限才能释放内存"})
        result.after = status()
        result.seconds = time.time() - start
        return result
    enable_all_privileges()

    def step(name: str, fn: Any) -> None:
        if progress:
            try:
                progress(name)
            except Exception:  # noqa: BLE001
                pass
        try:
            ok = bool(fn())
        except Exception as exc:  # noqa: BLE001
            ok = False
            name = f"{name}（{exc}）"
        result.steps.append({"name": name, "ok": ok})

    step("启用系统特权", lambda: True)
    if level in ("gentle", "standard", "deep"):
        step("清空系统工作集", empty_all_working_sets)
        result.trimmed = trim_working_sets(progress=progress)
        result.steps.append({"name": f"修剪 {result.trimmed} 个进程工作集",
                             "ok": result.trimmed > 0})
    if level in ("standard", "deep"):
        step("刷新已修改页面", flush_modified_pages)
        step("清空待机列表（缓存页）", purge_standby_list)
    if level == "deep":
        step("合并内存列表", combine_memory_lists)
        step("限制文件系统缓存", set_file_cache_limit)
    time.sleep(0.6)
    result.after = status()
    result.seconds = time.time() - start
    core.log(f"内存释放[{level}]：释放 "
             f"{core.human_size(result.freed)}（修剪 {result.trimmed} 个进程）",
             source="memory")
    return result


def top_processes(limit: int = 12) -> list[dict[str, Any]]:
    """占用内存最多的进程。"""
    rows: list[dict[str, Any]] = []
    try:
        import psutil
    except ImportError:
        return rows
    for proc in psutil.process_iter(["pid", "name", "memory_info", "exe"]):
        try:
            info = proc.info
            mem = info.get("memory_info")
            if not mem:
                continue
            rows.append({"pid": info["pid"], "name": info.get("name") or "",
                         "rss": int(getattr(mem, "rss", 0)),
                         "vms": int(getattr(mem, "vms", 0)),
                         "exe": info.get("exe") or ""})
        except Exception:  # noqa: BLE001
            continue
    rows.sort(key=lambda r: r["rss"], reverse=True)
    return rows[:limit]


def auto_config() -> dict[str, Any]:
    cfg = core.load_config()
    return {
        "auto_release": bool(cfg.get("auto_release", False)),
        "auto_threshold": int(cfg.get("auto_threshold", 85) or 85),
        "auto_interval": int(cfg.get("auto_interval", 300) or 300),
        "auto_level": cfg.get("auto_level", "standard"),
    }


class AutoReleaser:
    """后台自动释放：内存占用超过阈值时触发。"""

    def __init__(self, notify: Any = None) -> None:
        self.notify = notify
        self.last_run = 0.0
        self.last_percent = 0.0
        self.runs = 0
        self.last_freed = 0

    def maybe_release(self) -> dict[str, Any] | None:
        cfg = auto_config()
        if not cfg["auto_release"]:
            return None
        st = status()
        self.last_percent = st.percent
        if st.percent < cfg["auto_threshold"]:
            return None
        now = time.time()
        if now - self.last_run < cfg["auto_interval"]:
            return None
        self.last_run = now
        before = st.percent
        result = release(level=cfg["auto_level"])
        self.runs += 1
        self.last_freed = result.freed
        core.log_event("memory_auto_release",
                       {"before": before, "after": result.after.percent,
                        "freed": result.freed})
        if self.notify:
            try:
                self.notify("已自动释放内存",
                            f"内存占用 {before:.0f}% → {result.after.percent:.0f}%，"
                            f"释放 {core.human_size(result.freed)}")
            except Exception:  # noqa: BLE001
                pass
        return result.to_dict()
