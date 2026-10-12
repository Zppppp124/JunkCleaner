"""通过 nvapi_QueryInterface 探测 NVAPI 可用接口。

NVAPI 只导出 nvapi_QueryInterface / nvapi_Direct_GetMethod，
所有功能都要用「接口 ID」查询函数指针。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

NVAPI = Path(r"C:\Windows\System32\nvapi64.dll")

# 常用 NVAPI 接口 ID（来自公开的 NVAPI 头文件定义）
IDS = {
    "Initialize": 0x0150E828,
    "Unload": 0xD22BDD7E,
    "EnumPhysicalGPUs": 0xE5AC921F,
    "GPU_GetFullName": 0xCEEE8E9F,
    # 监控 / 电压
    "GPU_GetVoltageDomainsStatus": 0x0D9C8D3E,
    "GPU_GetCurrentVoltage": 0x9E1C1F61,
    "GPU_GetVoltageDomainStatus": 0x0D9C8D3E,
    "GPU_ClientVoltRailsGetStatus": 0x56739F12,
    "GPU_GetCoolerSettings": 0xDA141340,
    "GPU_SetCoolerLevels": 0x891FA0AE,
    "GPU_GetThermalSettings": 0xE3640A56,
    "GPU_SetThermalSettings": 0x32EE2FC9,
    # 频率 / Pstates（超频核心入口）
    "GPU_SetPstates20": 0x0F4DAE6B,
    "GPU_GetPstates20": 0x6FF81213,
    "GPU_SetPstates20v2": 0x4D2F8F2B,
    "GPU_GetPstatesInfoEx": 0x15D6A1B6,
    "GPU_SetClockBoost": 0x0E0F1B5B,
    "GPU_GetClockBoost": 0x0E0F1B5B,
    # 功耗
    "GPU_ClientPowerPoliciesGetStatus": 0x3F6E43AE,
    "GPU_ClientPowerPoliciesSetStatus": 0x4D2F8F2B,
}


def main() -> int:
    if not NVAPI.exists():
        print("nvapi64.dll 不存在")
        return 1
    nv = ctypes.WinDLL(str(NVAPI))

    # nvapi_QueryInterface(接口ID) -> void*
    qi = nv.nvapi_QueryInterface
    qi.argtypes = [ctypes.c_uint32]
    qi.restype = ctypes.c_void_p

    print("=" * 72)
    print("探测 NVAPI 接口（返回非 0 表示可用）")
    print("=" * 72)
    available = {}
    for name, iid in IDS.items():
        addr = qi(iid)
        available[name] = bool(addr)
        print(f"  {'可用' if addr else '不可用'}  {name:<38} "
              f"0x{iid:08X}  {hex(addr) if addr else ''}")

    print("=" * 72)
    # 初始化并枚举 GPU
    init = qi(IDS["Initialize"])
    if init:
        f_init = ctypes.CFUNCTYPE(ctypes.c_int)(init)
        rc = f_init()
        print(f"nvapi_Initialize via QueryInterface -> {rc}")
    else:
        print("Initialize 接口不可用")
        return 1

    enum = qi(IDS["EnumPhysicalGPUs"])
    if enum:
        f_enum = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(ctypes.c_int))(enum)
        handles = (ctypes.c_void_p * 64)()
        count = ctypes.c_int(0)
        rc = f_enum(handles, ctypes.byref(count))
        print(f"EnumPhysicalGPUs -> rc={rc} GPU数={count.value}")

        getname = qi(IDS["GPU_GetFullName"])
        if getname:
            f_name = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                                      ctypes.c_char_p)(getname)
            for i in range(count.value):
                buf = ctypes.create_string_buffer(64)
                r = f_name(handles[i], buf)
                print(f"  GPU{i}: {buf.value.decode('ascii', 'replace')} rc={r}")

    print("=" * 72)
    print("结论")
    print("=" * 72)
    voltage = [k for k in ("GPU_GetVoltageDomainsStatus",
                           "GPU_GetCurrentVoltage",
                           "GPU_ClientVoltRailsGetStatus") if available.get(k)]
    fan = [k for k in ("GPU_SetCoolerLevels", "GPU_GetCoolerSettings")
           if available.get(k)]
    pstate = [k for k in ("GPU_SetPstates20", "GPU_GetPstates20",
                          "GPU_SetPstates20v2") if available.get(k)]
    print(f"  电压读取接口: {voltage or '无'}")
    print(f"  风扇控制接口: {fan or '无'}")
    print(f"  Pstates(超频)接口: {pstate or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
