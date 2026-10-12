"""通过 MSI Afterburner 监控共享内存读取 GPU 实时状态。

Afterburner 的硬件监控服务会把每个数据源写入一块名为
      MAHMSharedMemory
的共享内存（格式见安装目录 SDK\\Include\\MAHMSharedMemory.h）。
这里直接用 ctypes 映射它，拿到真实的核心频率、核心电压、功耗、
温度、占用率等，而不是从旧 Profile 文件里推算。

注意：
  * 共享内存里 voltage 的原始值是 mV（例如 815.0）。
  * Afterburner 未运行时可能读不到签名，此时返回空状态。
"""

from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from typing import Any

SHARED_NAME = "MAHMSharedMemory"
SIGNATURE = 0x4D41484D          # 'MAHM'
DEAD = 0xDEAD
MAX_PATH = 260

# 数据源 ID（取自 SDK 头文件）
ID_GPU_TEMPERATURE = 0x00000000
ID_FAN_SPEED = 0x00000010
ID_CORE_CLOCK = 0x00000020
ID_MEMORY_CLOCK = 0x00000022
ID_GPU_USAGE = 0x00000030
ID_GPU_VOLTAGE = 0x00000040
ID_GPU_ABS_POWER = 0x00000061
ID_GPU_POWER_LIMIT = 0x00000071
ID_GPU_VOLTAGE_LIMIT = 0x00000072


class MAHM_HEADER(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwVersion", wintypes.DWORD),
        ("dwHeaderSize", wintypes.DWORD),
        ("dwNumEntries", wintypes.DWORD),
        ("dwEntrySize", wintypes.DWORD),
        ("time", ctypes.c_int32),
        ("dwNumGpuEntries", wintypes.DWORD),
        ("dwGpuEntrySize", wintypes.DWORD),
    ]


class MAHM_ENTRY(ctypes.Structure):
    _fields_ = [
        ("szSrcName", ctypes.c_char * MAX_PATH),
        ("szSrcUnits", ctypes.c_char * MAX_PATH),
        ("szLocalizedSrcName", ctypes.c_char * MAX_PATH),
        ("szLocalizedSrcUnits", ctypes.c_char * MAX_PATH),
        ("szRecommendedFormat", ctypes.c_char * MAX_PATH),
        ("data", ctypes.c_float),
        ("minLimit", ctypes.c_float),
        ("maxLimit", ctypes.c_float),
        ("dwFlags", wintypes.DWORD),
        ("dwGpu", wintypes.DWORD),
        ("dwSrcId", wintypes.DWORD),
    ]


FILE_MAP_READ = 0x0004


def _open_view() -> tuple[int, int] | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenFileMappingW.restype = wintypes.HANDLE
    kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                          wintypes.LPCWSTR]
    kernel32.MapViewOfFile.restype = wintypes.LPVOID
    kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                       wintypes.DWORD, wintypes.DWORD,
                                       ctypes.c_size_t]
    handle = kernel32.OpenFileMappingW(FILE_MAP_READ, False, SHARED_NAME)
    if not handle:
        return None
    view = kernel32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
    if not view:
        kernel32.CloseHandle(handle)
        return None
    return int(handle), int(view)


def _close_view(handle: int, view: int) -> None:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.UnmapViewOfFile.argtypes = [wintypes.LPVOID]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.UnmapViewOfFile(ctypes.c_void_p(view))
        kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001
        pass


def read_raw() -> dict[str, Any]:
    """读取一次共享内存，返回 {src_id: data} 与 GPU 名称。"""
    opened = _open_view()
    if opened is None:
        return {"ok": False, "error": "无法打开 Afterburner 监控共享内存"}
    handle, view = opened
    try:
        header = MAHM_HEADER.from_address(view)
        if header.dwSignature == DEAD:
            return {"ok": False, "error": "Afterburner 监控正在关闭"}
        if header.dwSignature != SIGNATURE:
            return {"ok": False, "error": "共享内存签名无效（Afterburner 未运行？）"}
        header_size = int(header.dwHeaderSize) or ctypes.sizeof(MAHM_HEADER)
        entry_size = int(header.dwEntrySize) or ctypes.sizeof(MAHM_ENTRY)
        count = int(header.dwNumEntries)
        values: dict[int, float] = {}
        for i in range(count):
            addr = view + header_size + i * entry_size
            entry = MAHM_ENTRY.from_address(addr)
            try:
                src_id = int(entry.dwSrcId)
                gpu = int(entry.dwGpu)
                value = float(entry.data)
            except Exception:  # noqa: BLE001
                continue
            # 只取第一块 GPU（dwGpu == 0）
            if gpu not in (0, 0xFFFFFFFF):
                continue
            # FLT_MAX 表示当前不可用
            if value == 3.4028234663852886e38:
                continue
            values.setdefault(src_id, value)
        return {"ok": True, "values": values,
                "count": count, "time": int(header.time)}
    finally:
        _close_view(handle, view)


def read_state() -> dict[str, Any]:
    """读取一份对界面友好的实时状态。"""
    raw = read_raw()
    if not raw.get("ok"):
        return {"ok": False, "error": raw.get("error", "")}
    v = raw["values"]

    def get(src_id: int, default: float = 0.0) -> float:
        return float(v.get(src_id, default))

    return {
        "ok": True,
        "clock_mhz": int(round(get(ID_CORE_CLOCK))),
        "mem_clock_mhz": int(round(get(ID_MEMORY_CLOCK))),
        "voltage_mv": round(get(ID_GPU_VOLTAGE), 1),
        "power_w": round(get(ID_GPU_ABS_POWER), 1),
        "power_limit_pct": round(get(ID_GPU_POWER_LIMIT), 1),
        "temperature_c": int(round(get(ID_GPU_TEMPERATURE))),
        "fan_pct": int(round(get(ID_FAN_SPEED))),
        "usage_pct": int(round(get(ID_GPU_USAGE))),
        "voltage_limited": bool(get(ID_GPU_VOLTAGE_LIMIT)),
        "source": "afterburner-shared-memory",
    }


def available() -> bool:
    return bool(read_raw().get("ok"))
