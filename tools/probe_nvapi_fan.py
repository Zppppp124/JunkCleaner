"""精确定位 NVAPI 风扇结构体的正确版本与布局。"""

from __future__ import annotations

import ctypes
from pathlib import Path

NVAPI = Path(r"C:\Windows\System32\nvapi64.dll")


class Cooler(ctypes.Structure):
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


class CoolerSettings(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint32),
        ("count", ctypes.c_uint32),
        ("cooler", ctypes.POINTER(Cooler)),
    ]


def main() -> int:
    nv = ctypes.WinDLL(str(NVAPI))
    qi = nv.nvapi_QueryInterface
    qi.argtypes = [ctypes.c_uint32]
    qi.restype = ctypes.c_void_p
    init = qi(0x0150E828)
    ctypes.CFUNCTYPE(ctypes.c_int)(init)()
    enum = qi(0xE5AC921F)
    handles = (ctypes.c_void_p * 64)()
    cnt = ctypes.c_int(0)
    ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                     ctypes.POINTER(ctypes.c_int))(enum)(handles, ctypes.byref(cnt))
    gpu = handles[0]
    addr = qi(0xDA141340)
    fn = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                          ctypes.POINTER(CoolerSettings))(addr)

    print(f"sizeof(Cooler)={ctypes.sizeof(Cooler)}  "
          f"sizeof(CoolerSettings)={ctypes.sizeof(CoolerSettings)}")
    print("尝试不同的 version 构造与结构体大小：")
    for size in (ctypes.sizeof(CoolerSettings), 16, 24, 32):
        for ver in (1, 2):
            arr = (Cooler * 4)()
            cs = CoolerSettings()
            cs.version = (ver << 16) | size
            cs.count = 0
            cs.cooler = ctypes.cast(arr, ctypes.POINTER(Cooler))
            rc = fn(gpu, 0, ctypes.byref(cs))
            mark = " <== OK" if rc == 0 else ""
            print(f"  size={size:<3} ver={ver} -> rc={rc}"
                  f"  count={cs.count}{mark}")
            if rc == 0:
                for i in range(min(int(cs.count), 4)):
                    c = arr[i]
                    print(f"      cooler[{i}] type={c.type} policy={c.currentPolicy} "
                          f"level={c.currentLevel} min={c.minLevel} max={c.maxLevel}")
                return 0

    # 直接尝试「不设 version」的旧式调用
    arr = (Cooler * 4)()
    cs = CoolerSettings()
    cs.version = 0
    cs.count = 0
    cs.cooler = ctypes.cast(arr, ctypes.POINTER(Cooler))
    print(f"\nversion=0 -> rc={fn(gpu, 0, ctypes.byref(cs))} count={cs.count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
