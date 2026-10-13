"""硬件信息：CPU / 主板 / 内存（自研实现，替代 CPU-Z 的信息功能）。

数据来源全部是公开接口：
  * 注册表 / Win32_Processor（型号名、核心数、缓存）
  * 注册表 VendorIdentifier（等价于 CPUID 厂商串）
  * Win32_BaseBoard / Win32_BIOS（主板、BIOS）
  * SMBIOS Type 17（内存条：slot 容量 频率 厂商 型号 电压）

为什么不用 CPU-Z：它是 CPUID 公司的专有软件，许可禁止再分发。
它显示的信息本来就来自上面这些公开来源，自研即可等价获取。
"""

from __future__ import annotations

import ctypes
import json
import re
import struct
from dataclasses import dataclass, field, asdict
from typing import Any

from . import core


def current_freq_mhz() -> int:
    """读取 CPU 当前实际运行频率（MHz）。

    为什么不直接用注册表 ~MHz 或 Win32_Processor.CurrentClockSpeed：
    那两项在多数机器上返回的是**基准频率**（本例 3418 / 3401 MHz），
    与实时运行频率无关，所以界面上看到的永远是基础频率。

    这里用 Windows 性能计数器 `% Processor Performance`（相对基准频率的
    百分比）换算：实测本机空闲时约 5.2 GHz、基准 3.4 GHz。
    """
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            base, _ = winreg.QueryValueEx(k, "~MHz")
            base = int(base)
    except OSError:
        return 0
    if base <= 0:
        return 0
    # 优先用性能计数器（能反映睿频）
    try:
        proc = core.run_powershell(
            "[int]((Get-Counter "
            "'\\Processor Information(_Total)\\% Processor Performance' "
            "-ErrorAction SilentlyContinue).CounterSamples.CookedValue)",
            timeout=20)
        text = (proc.stdout or b"").decode("utf-8", "replace").strip()
        pct = int(float(text))
        if pct > 0:
            mhz = int(base * pct / 100.0)
            if 100 <= mhz <= 10000:
                return mhz
    except Exception:  # noqa: BLE001
        pass
    # 退回 CallNtPowerInformation（部分机器能反映实时值）
    try:
        import ctypes
        from ctypes import wintypes

        class _PPI(ctypes.Structure):
            _fields_ = [("Number", wintypes.ULONG), ("MaxMhz", wintypes.ULONG),
                        ("CurrentMhz", wintypes.ULONG),
                        ("MhzLimit", wintypes.ULONG),
                        ("MaxIdleState", wintypes.ULONG),
                        ("CurrentIdleState", wintypes.ULONG)]

        n = max(1, ctypes.windll.kernel32.GetActiveProcessorCount(0))
        buf = (_PPI * n)()
        st = ctypes.windll.powrprof.CallNtPowerInformation(
            11, None, 0, ctypes.byref(buf), ctypes.sizeof(buf))
        if st == 0:
            mhz = int(sum(r.CurrentMhz for r in buf) / n)
            if mhz > 0:
                return mhz
    except Exception:  # noqa: BLE001
        pass
    return base


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------
@dataclass
class CpuInfo:
    name: str = ""
    vendor: str = ""
    identifier: str = ""
    cores: int = 0
    threads: int = 0
    base_mhz: int = 0
    max_mhz: int = 0
    current_mhz: int = 0
    l2_kb: int = 0
    l3_kb: int = 0
    architecture: str = ""
    features: list[str] = field(default_factory=list)
    microcode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vendor_string() -> str:
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            vendor, _ = winreg.QueryValueEx(k, "VendorIdentifier")
            return str(vendor).strip()
    except OSError:
        return ""


def _detect_features() -> list[str]:
    """检测常见指令集（用 IsProcessorFeaturePresent）。"""
    feats: list[str] = []
    k32 = ctypes.windll.kernel32
    for name, idx in (("SSE2", 10), ("SSE3", 13), ("AVX", 39), ("AVX2", 40)):
        try:
            if k32.IsProcessorFeaturePresent(idx):
                feats.append(name)
        except Exception:  # noqa: BLE001
            continue
    import os
    if os.environ.get("PROCESSOR_ARCHITECTURE", "").upper() == "AMD64":
        feats.append("x86-64")
    return feats


def collect_cpu() -> CpuInfo:
    info = CpuInfo()
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$p=Get-CimInstance Win32_Processor | Select-Object -First 1;"
        "$mc=(Get-ItemProperty 'HKLM:\\HARDWARE\\DESCRIPTION\\System\\"
        "CentralProcessor\\0' -Name 'Update Revision' "
        "-ErrorAction SilentlyContinue).'Update Revision';"
        "[pscustomobject]@{"
        "Name=$p.Name;Identifier=$p.ProcessorId;"
        "Cores=$p.NumberOfCores;Threads=$p.NumberOfLogicalProcessors;"
        "Base=[int]$p.MaxClockSpeed;"
        "L2=[int]$p.L2CacheSize;L3=[int]$p.L3CacheSize;"
        "Arch=$p.AddressWidth;Microcode=($mc -join ',')"
        "} | ConvertTo-Json -Compress")
    text = (core.run_powershell(script, timeout=60).stdout or b"").decode(
        "utf-8", "replace").strip()
    try:
        d = json.loads(text)
    except ValueError:
        d = {}
    info.name = str(d.get("Name") or "").strip()
    info.identifier = str(d.get("Identifier") or "")
    info.cores = int(d.get("Cores") or 0)
    info.threads = int(d.get("Threads") or 0)
    info.base_mhz = int(d.get("Base") or 0)
    info.l2_kb = int(d.get("L2") or 0)
    info.l3_kb = int(d.get("L3") or 0)
    width = int(d.get("Arch") or 0)
    info.architecture = f"{width}-bit" if width else ""
    mc = str(d.get("Microcode") or "").strip()
    if mc and mc != "0":
        try:
            parts = [int(x) for x in mc.split(",") if x.strip()]
            if len(parts) >= 4:
                info.microcode = f"0x{parts[1] << 24 | parts[0]:08X}"
        except ValueError:
            info.microcode = mc

    info.vendor = _vendor_string()
    if not info.vendor:
        if "Intel" in info.name:
            info.vendor = "GenuineIntel"
        elif "AMD" in info.name:
            info.vendor = "AuthenticAMD"

    info.max_mhz = info.base_mhz
    for pat in (r"@\s*([\d.]+)\s*GHz", r"([\d.]+)\s*GHz"):
        m = re.search(pat, info.name)
        if m:
            try:
                info.max_mhz = int(float(m.group(1)) * 1000)
            except ValueError:
                pass
            break
    info.current_mhz = current_freq_mhz()
    info.features = _detect_features()
    return info


# --------------------------------------------------------------------------
# 主板 / BIOS
# --------------------------------------------------------------------------
@dataclass
class BoardInfo:
    board_vendor: str = ""
    board_name: str = ""
    board_version: str = ""
    bios_vendor: str = ""
    bios_version: str = ""
    bios_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_board() -> BoardInfo:
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$b=Get-CimInstance Win32_BaseBoard | Select-Object -First 1;"
        "$s=Get-CimInstance Win32_BIOS | Select-Object -First 1;"
        "[pscustomobject]@{BV=$b.Manufacturer;BN=$b.Product;"
        "BVer=$b.Version;SV=$s.Manufacturer;SN=$s.Name;SD=$s.ReleaseDate}"
        " | ConvertTo-Json -Compress")
    text = (core.run_powershell(script, timeout=60).stdout or b"").decode(
        "utf-8", "replace").strip()
    try:
        d = json.loads(text)
    except ValueError:
        d = {}
    date_str = ""
    date = d.get("SD")
    if isinstance(date, str) and date.startswith("/Date("):
        m = re.search(r"/Date\((\d+)", date)
        if m:
            import datetime as _dt
            try:
                date_str = _dt.datetime.fromtimestamp(
                    int(m.group(1)) / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                date_str = ""
    return BoardInfo(
        board_vendor=str(d.get("BV") or "").strip(),
        board_name=str(d.get("BN") or "").strip(),
        board_version=str(d.get("BVer") or "").strip(),
        bios_vendor=str(d.get("SV") or "").strip(),
        bios_version=str(d.get("SN") or "").strip(),
        bios_date=date_str,
    )


# --------------------------------------------------------------------------
# 内存（SMBIOS Type 17）
# --------------------------------------------------------------------------
@dataclass
class DimmInfo:
    slot: str = ""
    capacity_gb: float = 0.0
    speed_mhz: int = 0
    configured_mhz: int = 0
    manufacturer: str = ""
    part_number: str = ""
    serial: str = ""
    voltage_mv: int = 0
    form_factor: str = ""
    mem_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FORM_FACTORS = {8: "DIMM", 12: "SODIMM", 13: "SRIMM", 2: "SIP"}
MEM_TYPES = {24: "DDR3", 26: "DDR4", 34: "DDR5", 20: "DDR2"}


def _smbios_strings(data: bytes, offset: int) -> list[str]:
    n = data[offset]
    pos = offset + n
    out: list[str] = []
    while pos < len(data):
        end = data.find(b"\0", pos)
        if end < 0 or end == pos:
            break
        out.append(data[pos:end].decode("utf-8", "replace"))
        pos = end + 1
    return out


def _walk_smbios() -> list[tuple[bytes, list[str]]]:
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$t=Get-CimInstance -ClassName Win32_SystemFirmwareTable "
        "-Namespace root\\wmi -ErrorAction SilentlyContinue;"
        "$d=(Get-CimInstance Win32_SystemFirmwareTable | "
        "Where-Object {$_.FirmwareTableProviderSignature -eq 1381190978} | "
        "Select-Object -First 1).FirmwareTable;"
        "if($d){[Convert]::ToBase64String($d)}else{''}")
    text = (core.run_powershell(script, timeout=90).stdout or b"").decode(
        "utf-8", "replace").strip()
    if not text:
        return []
    import base64
    try:
        data = base64.b64decode(text)
    except Exception:  # noqa: BLE001
        return []
    out: list[tuple[bytes, list[str]]] = []
    pos = 0
    while pos + 4 <= len(data):
        slen = data[pos + 1]
        if slen < 4 or pos + slen > len(data):
            break
        raw = data[pos:pos + slen]
        out.append((raw, _smbios_strings(data, pos)))
        p = pos + slen
        while p + 1 < len(data) and not (data[p] == 0 and data[p + 1] == 0):
            p += 1
        pos = p + 2
    return out


def collect_memory() -> list[DimmInfo]:
    dimms: list[DimmInfo] = []
    try:
        for raw, strings in _walk_smbios():
            if not raw or raw[0] != 17 or len(raw) < 0x15:
                continue

            def s(idx: int) -> str:
                return strings[idx - 1].strip() if 1 <= idx <= len(strings) else ""

            size = struct.unpack_from("<H", raw, 0x0C)[0]
            if size in (0, 0xFFFF):
                cap_gb = 0.0
            elif size & 0x8000:
                cap_gb = (size & 0x7FFF) / 1024.0
            else:
                cap_gb = size / 1024.0
            speed = struct.unpack_from("<H", raw, 0x15)[0]
            configured = (struct.unpack_from("<H", raw, 0x20)[0]
                          if len(raw) > 0x22 else 0) or speed
            dimms.append(DimmInfo(
                slot=s(raw[0x10]) or f"DIMM{len(dimms)}",
                capacity_gb=round(cap_gb, 1),
                speed_mhz=int(speed),
                configured_mhz=int(configured),
                manufacturer=s(raw[0x17]),
                part_number=s(raw[0x1A]),
                serial=s(raw[0x18]),
                voltage_mv=int(struct.unpack_from("<H", raw, 0x18)[0]),
                form_factor=FORM_FACTORS.get(raw[0x0E], str(raw[0x0E])),
                mem_type=MEM_TYPES.get(raw[0x12], f"type{raw[0x12]}"),
            ))
    except Exception as exc:  # noqa: BLE001
        core.log(f"SMBIOS 内存解析失败：{exc}", level="WARN", source="hw")

    if dimms:
        return dimms

    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-CimInstance Win32_PhysicalMemory | "
        "Select-Object BankLabel,Capacity,Speed,ConfiguredClockSpeed,"
        "Manufacturer,PartNumber,SerialNumber,ConfiguredVoltage,SMBIOSMemoryType"
        " | ConvertTo-Json -Compress")
    text = (core.run_powershell(script, timeout=60).stdout or b"").decode(
        "utf-8", "replace").strip()
    try:
        rows = json.loads(text)
    except ValueError:
        return dimms
    if isinstance(rows, dict):
        rows = [rows]
    for i, r in enumerate(rows or []):
        dimms.append(DimmInfo(
            slot=str(r.get("BankLabel") or f"DIMM{i}"),
            capacity_gb=round(int(r.get("Capacity") or 0) / (1 << 30), 1),
            speed_mhz=int(r.get("Speed") or 0),
            configured_mhz=int(r.get("ConfiguredClockSpeed") or 0),
            manufacturer=str(r.get("Manufacturer") or "").strip(),
            part_number=str(r.get("PartNumber") or "").strip(),
            serial=str(r.get("SerialNumber") or "").strip(),
            voltage_mv=int(r.get("ConfiguredVoltage") or 0),
            mem_type=MEM_TYPES.get(int(r.get("SMBIOSMemoryType") or 0), ""),
        ))
    return dimms


def collect_all() -> dict[str, Any]:
    return {
        "cpu": collect_cpu().to_dict(),
        "board": collect_board().to_dict(),
        "memory": [d.to_dict() for d in collect_memory()],
    }
