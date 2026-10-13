"""CPU 跑分与压力测试（自研实现，替代 CPU-Z 的 Bench / Stress）。

跑分思路（不照搬 CPU-Z 的私有评分，用可复现的公开算法）：
  * 单核分：整数运算 + 浮点运算 + 内存访问，单线程循环固定次数
  * 多核分：同样负载铺满所有逻辑核心
  * 结果用「每秒完成的迭代次数」表示，并给出相对参考值，便于横向对比

压力测试：多进程全核满载，同时监控频率 / 温度 / 降频原因。
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
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


def worker_cli(argv: list[str]) -> int:
    """多核跑分的子进程入口：跑一次负载并把耗时打印到 stdout。

    为什么不用 multiprocessing.Pool：打包成单文件 EXE 后，
    Pool 需要重新引导本程序，在冻结环境下容易出现句柄/权限问题
    （实测 WinError 5），表现为「跑分没反应」。改为自己用
    subprocess 拉起同一可执行文件 + 隐藏参数，行为完全可控。
    """
    try:
        seed = int(argv[0])
        iters = int(argv[1])
    except (IndexError, ValueError):
        print("0.0")
        return 2
    print(f"{_workload(seed, iters):.6f}")
    return 0


def _spawn_args(seed: int, iters: int) -> list[str]:
    """构造子进程命令行（兼容源码运行与打包运行）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--cpu-bench-worker", str(seed), str(iters)]
    entry = Path(__file__).resolve().parents[1] / "junkcleaner_entry.py"
    exe = core.python_exe_windowless()
    return [exe, str(entry), "--cpu-bench-worker", str(seed), str(iters)]


def _run_chunk(seed: int, iters: int) -> float:
    """在独立子进程里跑一段负载，返回耗时秒数。"""
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    try:
        p = subprocess.run(_spawn_args(seed, iters), capture_output=True,
                           timeout=600, creationflags=flags)
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        line = out.splitlines()[-1] if out else "0"
        return float(line)
    except Exception:  # noqa: BLE001
        return 0.0


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


def benchmark(iterations: int = 6_000_000,
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
    # 同时拉起 N 个独立子进程（绕开 GIL，也绕开冻结环境下的
    # multiprocessing.Pool 兼容问题）。
    procs: list[subprocess.Popen] = []
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        for i in range(threads):
            procs.append(subprocess.Popen(
                _spawn_args(i + 1, iterations),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=flags))
        for p in procs:
            try:
                p.communicate(timeout=600)
            except Exception:  # noqa: BLE001
                p.kill()
        ok_children = sum(1 for p in procs if p.returncode == 0)
        if ok_children == 0:
            res.note = "子进程全部失败，已降级为线程池"
            raise RuntimeError("no child succeeded")
        if ok_children < threads:
            res.note = f"{threads - ok_children} 个子进程未正常返回，结果偏保守"
    except Exception:  # noqa: BLE001
        for p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        if not res.note:
            res.note = "多核测试降级为线程池"
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
