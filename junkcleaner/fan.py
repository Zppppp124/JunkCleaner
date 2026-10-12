"""风扇控制。

能力边界（本机实测）
-------------------
GPU 风扇：接口存在但**新版驱动拒绝**
    nvapi64.dll 里 GPU_GetCoolerSettings / GPU_SetCoolerLevels 确实导出，
    但实际调用一律返回 rc=-9（NVAPI_INCOMPATIBLE_STRUCT_VERSION），
    换遍 version/size 组合都无效。
    原因是 NVIDIA 从 R570 之后的驱动把用户态风扇/电压控制收紧到
    受签名保护的路径，普通进程无法再直接调用 —— 这正是
    MSI Afterburner 必须装自己的 RTCore 内核驱动的原因。
    当前驱动版本可通过 `nvidia-smi` 查询（本机为 617.42）。

    结论：**能用 NVAPI 走通风扇控制** 不成立；要么用 Afterburner
    （它自带驱动），要么装 HWiNFO + FanControl 这类自带驱动的方案。

主板 / CPU 风扇：**本机做不到**
    1. WMI 的 Win32_Fan 返回 0 个设备，Win32_TemperatureProbe 也是 0。
       华硕消费级主板不在 ACPI 里暴露风扇转速，标准接口读不到。
    2. 真正能控制的是华硕 AsIO 驱动（AsIO3.sys / AsIO2.sys），
       本机没有安装（没装 AI Suite / Armoury Crate）。
    3. 系统里虽有一个 PawnIO.sys，但它来自飞智手柄驱动
       （D:\\Program Files\\Flydigi Space Station\\Driver\\PawnIO.sys），
       不是硬件监控组件，不提供主板 Super-I/O 的寄存器定义。
    4. 要真正实现需要：装 AsIO 驱动 + 逆向 Super-I/O 芯片寄存器
       （B760-G 用的多为 Nuvoton NCT6798D 一类）。这属于主板厂商私有协议，
       没有公开文档，误写寄存器可能烧风扇或让主板不识别转速。

因此本模块提供：
  * GPU 风扇：能力探测（如实报告可用性）+ 曲线计算逻辑
    （一旦环境具备（旧驱动或 Afterburner 在运行）即可用）
  * CPU 风扇：只读可读性检测 + 可行路径说明
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from . import core

NVAPI = Path(r"C:\Windows\System32\nvapi64.dll")
NVAPI_COOLER_ID = 0xDA141340          # GPU_GetCoolerSettings
NVAPI_SET_COOLER = 0x891FA0AE         # GPU_SetCoolerLevels
NVAPI_ENUM_GPU = 0xE5AC921F
NVAPI_INIT = 0x0150E828

NVAPI_COOLER_POLICY_AUTO = 0x00000008
NVAPI_COOLER_POLICY_MANUAL = 0x00000004


class _Cooler(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("controller", ctypes.c_int),
        ("defaultPolicy", ctypes.c_uint32),
        ("currentPolicy", ctypes.c_uint32),
        ("currentLevel", ctypes.c_uint32),
        ("defaultLevel", ctypes.c_uint32),
        ("minLevel", ctypes.c_uint32),
        ("maxLevel", ctypes.c_uint32),
    ]


class _CoolerSettings(ctypes.Structure):
    # NVAPI 的 cooler 字段是「指针 + 数量」，不是内联数组
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
        ("cooler", ctypes.POINTER(_Cooler)),
    ]


class _CoolerLevel(ctypes.Structure):
    _fields_ = [("coolerId", ctypes.c_uint32),
                ("policy", ctypes.c_uint32),
                ("level", ctypes.c_uint32)]


class _CoolerLevels(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
        ("levels", ctypes.POINTER(_CoolerLevel)),
    ]


def nvapi_available() -> bool:
    return NVAPI.exists()


class NvFan:
    """通过 NVAPI 控制 GPU 风扇。"""

    def __init__(self) -> None:
        self._gpu: int = 0
        self._qi: Any = None
        self._ok = False
        self.error = ""
        self._init()

    def _init(self) -> None:
        if not nvapi_available():
            self.error = "nvapi64.dll 不存在"
            return
        try:
            nv = ctypes.WinDLL(str(NVAPI))
            qi = nv.nvapi_QueryInterface
            qi.argtypes = [ctypes.c_uint32]
            qi.restype = ctypes.c_void_p
            init = qi(NVAPI_INIT)
            if not init:
                self.error = "NVAPI 初始化接口不可用"
                return
            ctypes.CFUNCTYPE(ctypes.c_int)(init)()
            enum = qi(NVAPI_ENUM_GPU)
            handles = (ctypes.c_void_p * 64)()
            count = ctypes.c_int(0)
            ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_int))(enum)(
                handles, ctypes.byref(count))
            if count.value < 1:
                self.error = "未找到 NVIDIA GPU"
                return
            self._gpu = handles[0]
            self._qi = qi
            self._ok = True
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)

    @property
    def ok(self) -> bool:
        return self._ok

    def get(self) -> dict[str, Any]:
        if not self._ok:
            return {"ok": False, "error": self.error}
        addr = self._qi(NVAPI_COOLER_ID)
        if not addr:
            return {"ok": False, "error": "GetCoolerSettings 不可用"}
        fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                              ctypes.POINTER(_CoolerSettings))(addr)
        arr = (_Cooler * 4)()
        cs = _CoolerSettings()
        cs.version = (ctypes.sizeof(_CoolerSettings) | (1 << 16))
        cs.count = 0
        cs.cooler = ctypes.cast(arr, ctypes.POINTER(_Cooler))
        rc = fn(self._gpu, 0, ctypes.byref(cs))
        if rc != 0:
            return {"ok": False, "error": f"rc={rc}"}
        out = []
        for i in range(min(int(cs.count), 4)):
            c = arr[i]
            out.append({"index": i, "type": c.type,
                        "policy": "manual"
                        if c.currentPolicy == NVAPI_COOLER_POLICY_MANUAL
                        else "auto",
                        "level": c.currentLevel,
                        "min": c.minLevel, "max": c.maxLevel})
        return {"ok": True, "count": int(cs.count), "coolers": out}

    def set_percent(self, percent: int) -> dict[str, Any]:
        if not self._ok:
            return {"ok": False, "error": self.error}
        percent = max(0, min(100, int(percent)))
        addr = self._qi(NVAPI_SET_COOLER)
        if not addr:
            return {"ok": False, "error": "SetCoolerLevels 不可用"}
        fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                              ctypes.POINTER(_CoolerLevels))(addr)
        arr = (_CoolerLevel * 1)()
        arr[0].coolerId = 0
        arr[0].policy = NVAPI_COOLER_POLICY_MANUAL
        arr[0].level = percent
        lv = _CoolerLevels()
        lv.version = (ctypes.sizeof(_CoolerLevels) | (1 << 16))
        lv.count = 1
        lv.levels = ctypes.cast(arr, ctypes.POINTER(_CoolerLevel))
        rc = fn(self._gpu, 0, ctypes.byref(lv))
        ok = rc == 0
        core.log(f"GPU 风扇设为 {percent}%: {'成功' if ok else f'rc={rc}'}",
                 source="fan")
        return {"ok": ok, "percent": percent, "rc": rc}

    def set_auto(self) -> dict[str, Any]:
        if not self._ok:
            return {"ok": False, "error": self.error}
        addr = self._qi(NVAPI_SET_COOLER)
        fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                              ctypes.POINTER(_CoolerLevels))(addr)
        arr = (_CoolerLevel * 1)()
        arr[0].coolerId = 0
        arr[0].policy = NVAPI_COOLER_POLICY_AUTO
        arr[0].level = 0
        lv = _CoolerLevels()
        lv.version = (ctypes.sizeof(_CoolerLevels) | (1 << 16))
        lv.count = 1
        lv.levels = ctypes.cast(arr, ctypes.POINTER(_CoolerLevel))
        rc = fn(self._gpu, 0, ctypes.byref(lv))
        return {"ok": rc == 0, "rc": rc}


DEFAULT_CURVE = [
    (30, 30), (40, 35), (50, 45), (60, 60),
    (70, 80), (80, 95), (90, 100),
]


def interpolate(curve: list[tuple[int, int]], temp: int) -> int:
    """按温度线性插值出风扇转速。"""
    if not curve:
        return 50
    pts = sorted(curve)
    if temp <= pts[0][0]:
        return pts[0][1]
    if temp >= pts[-1][0]:
        return pts[-1][1]
    for (t0, f0), (t1, f1) in zip(pts, pts[1:]):
        if t0 <= temp <= t1:
            if t1 == t0:
                return f1
            ratio = (temp - t0) / (t1 - t0)
            return int(round(f0 + (f1 - f0) * ratio))
    return pts[-1][1]


@dataclass
class FanCurveState:
    enabled: bool = False
    curve: list[list[int]] | None = None
    last_temp: int = 0
    last_percent: int = 0
    updates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FanCurveController:
    """按 GPU 温度自动调风扇（曲线比例调节）。"""

    def __init__(self, fan: NvFan, curve: list[tuple[int, int]] | None = None,
                 interval: float = 5.0,
                 progress: Callable[[str], None] | None = None) -> None:
        self.fan = fan
        self.curve = curve or list(DEFAULT_CURVE)
        self.interval = interval
        self.progress = progress
        self.state = FanCurveState(curve=[list(p) for p in self.curve])
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_once(self) -> dict[str, Any]:
        from . import gpu
        st = gpu.read_state()
        temp = st.temperature
        pct = interpolate(self.curve, temp)
        r = self.fan.set_percent(pct)
        self.state.last_temp = temp
        self.state.last_percent = pct
        self.state.updates += 1
        if self.progress:
            try:
                self.progress(f"{temp}°C -> 风扇 {pct}%")
            except Exception:  # noqa: BLE001
                pass
        return {"ok": r.get("ok"), "temp": temp, "percent": pct}

    def run_forever(self) -> None:
        while not self._stop:
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001
                core.log(f"风扇曲线出错: {exc}", level="ERROR", source="fan")
            time.sleep(self.interval)


def cpu_fan_status() -> dict[str, Any]:
    """CPU / 主板风扇可读性检测（如实返回，不假装能控制）。"""
    info: dict[str, Any] = {
        "controllable": False,
        "readable": False,
        "fan_count": 0,
        "temp_probe_count": 0,
        "reasons": [],
        "requires": [],
    }
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "$f=(Get-CimInstance Win32_Fan | Measure-Object).Count;"
              "$t=(Get-CimInstance Win32_TemperatureProbe | Measure-Object).Count;"
              "'{0}|{1}' -f $f,$t")
    txt = (core.run_powershell(script, timeout=40).stdout or b"").decode(
        "utf-8", "replace").strip()
    try:
        f, t = (txt or "0|0").split("|")
        info["fan_count"] = int(f)
        info["temp_probe_count"] = int(t)
    except ValueError:
        pass
    info["readable"] = info["fan_count"] > 0

    has_asio = any(Path(p).exists() for p in
                   (r"C:\Windows\System32\drivers\AsIO3.sys",
                    r"C:\Windows\System32\drivers\AsIO2.sys"))
    if not has_asio:
        info["reasons"].append(
            "未安装华硕 AsIO 驱动（AsIO3.sys / AsIO2.sys），"
            "标准 WMI 读不到主板风扇")
    if info["fan_count"] == 0:
        info["reasons"].append("Win32_Fan 返回 0 个设备")
    info["requires"] = [
        "在 BIOS 用 Q-Fan 曲线控制（最稳，开机即生效）",
        "或安装华硕 AI Suite 3 / Armoury Crate（提供 AsIO 驱动）",
        "第三方方案：HWiNFO + FanControl（自带驱动与 Super-I/O 定义）",
    ]
    return info


def gpu_fan_status() -> dict[str, Any]:
    """GPU 风扇可用性探测（如实报告，不假装能控制）。"""
    info: dict[str, Any] = {
        "nvapi_present": nvapi_available(),
        "nvapi_callable": False,
        "controllable": False,
        "driver": "",
        "reason": "",
        "alternatives": [],
    }
    try:
        from . import gpu as _gpu
        st = _gpu.read_state()
        info["driver"] = st.driver
        info["current_percent"] = st.fan
    except Exception:  # noqa: BLE001
        pass

    if not info["nvapi_present"]:
        info["reason"] = "未找到 nvapi64.dll"
        return info

    f = NvFan()
    if not f.ok:
        info["reason"] = f.error
        return info
    r = f.get()
    if r.get("ok"):
        info["nvapi_callable"] = True
        info["controllable"] = True
        info["coolers"] = r.get("coolers")
        return info
    info["reason"] = (
        f"NVAPI 风扇接口不可用（{r.get('error')}）。"
        "NVIDIA R570+ 驱动已把用户态风扇控制收归签名路径，"
        "普通进程无法直接调用。")
    info["alternatives"] = [
        "用 MSI Afterburner（自带 RTCore 内核驱动）设置风扇曲线",
        "或用 HWiNFO + FanControl（同样自带驱动）",
        "BIOS 里的显卡风扇策略（部分非公卡支持）",
    ]
    return info


def status() -> dict[str, Any]:
    """风扇总体状态：CPU 与 GPU 分别报告。"""
    return {"cpu": cpu_fan_status(), "gpu": gpu_fan_status()}
