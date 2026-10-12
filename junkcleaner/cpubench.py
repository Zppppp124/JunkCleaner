"""CPU 跑分与压力测试（自研实现，替代 CPU-Z 的 Bench / Stress）。

跑分思路（不照搬 CPU-Z 的私有评分，用可复现的公开算法）：
  * 单核分：整数运算 + 浮点运算 + 内存访问，单线程循环固定次数
  * 多核分：同样负载铺满所有逻辑核心
  * 结果用「每秒完成的迭代次数」表示，并给出相对参考值，便于横向对比

压力测试：多进程全核满载，同时监控频率 / 温度 / 降频原因。
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from . import core


# --------------------------------------------------------------------------
# 工作负载
# --------------------------------------------------------------------------
def _workload(seed: int, iterations: int) -> float:
    """混合负载：整数、浮点、分支、内存。返回耗时秒数。"""
    t0 = time.perf_counter()
    acc_i = seed | 1
    acc_f = float(seed) * 0.5
    buf = [float((seed + i) % 97) for i in range(512)]
    for i in range(iterations):
        # 整数：乘加 + 位运算
        acc_i = (acc_i * 1103515245 + 12345) & 0x7FFFFFFF
        acc_i ^= (acc_i >> 7)
        # 浮点：乘加 + 开方
        acc_f = acc_f * 1.000001 + math.sqrt(abs(acc_f) + 1.0)
        # 内存：环形访问
        idx = (acc_i + i) & 511
        buf[idx] = buf[idx] * 0.5 + acc_f * 0.5
        # 分支：制造不可预测跳转
        if acc_i & 0x100:
            acc_f -= buf[idx] * 0.001
    total = sum(buf)
    return time.perf_counter() - t0 + (total * 1e-12)


def _worker(args: tuple[int, int]) -> float:
    seed, iters = args
    return _workload(seed, iters)


@dataclass
class BenchResult:
    single_score: float = 0.0
    multi_score: float = 0.0
    ratio: float = 0.0
    threads: int = 0
    single_seconds: float = 0.0
    multi_seconds: float = 0.0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def benchmark(iterations: int = 220_000,
              progress: Callable[[str], None] | None = None) -> BenchResult:
    """跑单核 + 多核基准。分数 = 每秒千次迭代（越高越快）。"""
    res = BenchResult()
    threads = os.cpu_count() or 1
    res.threads = threads

    def say(m: str) -> None:
        if progress:
            try:
                progress(m)
            except Exception:  # noqa: BLE001
                pass

    say("单核测试…")
    t0 = time.perf_counter()
    _workload(1, iterations)
    res.single_seconds = time.perf_counter() - t0
    res.single_score = iterations / max(1e-6, res.single_seconds) / 1000.0

    # 多核：用进程池（避免 GIL）
    say(f"多核测试（{threads} 线程）…")
    t0 = time.perf_counter()
    try:
        with mp.Pool(processes=threads) as pool:
            pool.map(_worker, [(i + 1, iterations) for i in range(threads)])
    except Exception as exc:  # noqa: BLE001
        res.note = f"多核测试降级为线程池：{exc}"
        ts = []
        for i in range(threads):
            t = threading.Thread(target=_workload, args=(i + 1, iterations))
            t.start()
            ts.append(t)
        for t in ts:
            t.join()
    res.multi_seconds = time.perf_counter() - t0
    res.multi_score = (iterations * threads) / max(1e-6, res.multi_seconds) / 1000.0
    res.ratio = (res.multi_score / res.single_score) if res.single_score else 0.0
    return res


# --------------------------------------------------------------------------
# CPU 压力测试 + 监控
# --------------------------------------------------------------------------
def _burn(stop_flag: Any, seed: int) -> None:
    """持续满载，直到 stop_flag 被设置。"""
    n = 0
    while not stop_flag.is_set():
        _workload(seed + n, 60000)
        n += 1


def _cpu_clock_mhz() -> int:
    """读当前 CPU 频率（性能计数器口径）。"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            mhz, _ = winreg.QueryValueEx(k, "~MHz")
            return int(mhz)
    except OSError:
        return 0


@dataclass
class StressSample:
    t: float
    load: float
    temp_c: int
    clock_mhz: int
    throttle: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cpu_stress(seconds: int = 60, threads: int = 0,
               progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """全核 CPU 压力测试，返回温度/频率/降频情况。"""
    threads = threads or (os.cpu_count() or 4)
    flag = mp.Event()
    procs: list[mp.Process] = []
    for i in range(threads):
        p = mp.Process(target=_burn, args=(flag, i * 7919), daemon=True)
        p.start()
        procs.append(p)

    samples: list[StressSample] = []
    start = time.time()
    try:
        # 用 psutil 读温度/占用
        import psutil
        while time.time() - start < seconds:
            try:
                temp = _read_cpu_temp()
            except Exception:  # noqa: BLE001
                temp = 0
            s = StressSample(
                t=round(time.time() - start, 1),
                load=psutil.cpu_percent(interval=1.0),
                temp_c=temp,
                clock_mhz=_cpu_clock_mhz(),
                throttle="",
            )
            samples.append(s)
            if progress:
                try:
                    progress(f"{s.load:.0f}%  {s.clock_mhz}MHz  "
                             f"{s.temp_c or '—'}°C  {int(s.t)}/{seconds}s")
                except Exception:  # noqa: BLE001
                    pass
    finally:
        flag.set()
        for p in procs:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()

    loads = [s.load for s in samples] or [0]
    temps = [s.temp_c for s in samples if s.temp_c] or [0]
    clocks = [s.clock_mhz for s in samples if s.clock_mhz] or [0]
    return {
        "seconds": seconds,
        "threads": threads,
        "samples": len(samples),
        "load_avg": round(sum(loads) / len(loads), 1),
        "load_min": min(loads),
        "temp_max": max(temps),
        "temp_avg": round(sum(temps) / len(temps), 1) if temps else 0,
        "clock_min": min(clocks),
        "clock_max": max(clocks),
        "detail": [s.to_dict() for s in samples[-8:]],
    }


def _read_cpu_temp() -> int:
    """读 CPU 温度。优先 WMI 热区，取不到返回 0。"""
    try:
        import wmi
        c = wmi.WMI(namespace="root\\WMI")
        zones = c.MSAcpi_ThermalZoneTemperature()
        best = 0
        for z in zones:
            if z.CurrentTemperature:
                cels = int(z.CurrentTemperature / 10.0 - 273.15)
                if 0 < cels < 120:
                    best = max(best, cels)
        return best
    except Exception:  # noqa: BLE001
        return 0
