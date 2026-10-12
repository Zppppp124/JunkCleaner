"""测量扫描过程中的 CPU 与硬盘占用。

CPU 使用率按任务管理器口径（相对整机逻辑核心数）给出，同时也给出
「占满几个核」的等效值。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psutil  # noqa: E402

from junkcleaner import core, scanner  # noqa: E402


class Sampler(threading.Thread):
    def __init__(self, pid: int, interval: float = 0.4, whole_system: bool = True) -> None:
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.interval = interval
        self.samples: list[tuple[float, float, float]] = []
        self.system_cpu: list[float] = []
        self.whole_system = whole_system
        self._stop = threading.Event()
        self.logical = psutil.cpu_count() or 1

    def run(self) -> None:
        self.proc.cpu_percent(None)
        psutil.cpu_percent(None)
        try:
            io = self.proc.io_counters()
            last_read, last_write = io.read_bytes, io.write_bytes
        except Exception:  # noqa: BLE001
            last_read = last_write = 0
        last = time.time()
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            now = time.time()
            dt = max(1e-6, now - last)
            last = now
            cpu = self.proc.cpu_percent(None)          # 单核百分比（100=一个核满载）
            if self.whole_system:
                self.system_cpu.append(psutil.cpu_percent(None))
            try:
                io = self.proc.io_counters()
                read = (io.read_bytes - last_read) / dt
                write = (io.write_bytes - last_write) / dt
                last_read, last_write = io.read_bytes, io.write_bytes
            except Exception:  # noqa: BLE001
                read = write = 0.0
            self.samples.append((cpu, read, write))

    def stop(self) -> None:
        self._stop.set()

    def summary(self) -> dict[str, float]:
        if not self.samples:
            return {}
        cpu = [s[0] for s in self.samples]
        read = [s[1] for s in self.samples]
        write = [s[2] for s in self.samples]
        cpu.sort()
        read.sort()
        write.sort()

        def pct(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            idx = min(len(values) - 1, int(len(values) * p))
            return values[idx]

        return {
            "seconds": float(len(self.samples)),
            # 任务管理器口径：单核% / 逻辑核心数
            "cpu_total_avg": sum(cpu) / len(cpu) / self.logical,
            "cpu_total_p50": pct(cpu, 0.5) / self.logical,
            "cpu_total_p95": pct(cpu, 0.95) / self.logical,
            "cpu_total_max": cpu[-1] / self.logical,
            "cpu_cores_avg": sum(cpu) / len(cpu) / 100.0,
            "cpu_cores_max": cpu[-1] / 100.0,
            "read_avg_mbps": sum(read) / len(read) / (1 << 20),
            "read_p95_mbps": pct(read, 0.95) / (1 << 20),
            "read_max_mbps": read[-1] / (1 << 20),
            "write_avg_mbps": sum(write) / len(write) / (1 << 20),
            "write_p95_mbps": pct(write, 0.95) / (1 << 20),
            "write_max_mbps": write[-1] / (1 << 20),
            "logical_cores": float(self.logical),
            "system_cpu_avg": (sum(self.system_cpu) / len(self.system_cpu)
                               if self.system_cpu else -1.0),
            "system_cpu_max": (max(self.system_cpu) if self.system_cpu else -1.0),
        }


def idle_baseline(seconds: float = 3.0) -> dict[str, float]:
    """空闲基线：扫描前先测一段时间，用于对比扫描带来的额外开销。"""
    psutil.cpu_percent(None)
    samples: list[float] = []
    t0 = time.time()
    io0 = psutil.disk_io_counters()
    while time.time() - t0 < seconds:
        time.sleep(0.4)
        samples.append(psutil.cpu_percent(None))
    io1 = psutil.disk_io_counters()
    dt = max(1e-6, time.time() - t0)
    return {
        "cpu_avg": sum(samples) / len(samples) if samples else 0.0,
        "cpu_max": max(samples) if samples else 0.0,
        "disk_read_mbps": (io1.read_bytes - io0.read_bytes) / dt / (1 << 20),
        "disk_write_mbps": (io1.write_bytes - io0.write_bytes) / dt / (1 << 20),
    }


class DiskSampler(threading.Thread):
    """全系统磁盘读写采样。"""

    def __init__(self, interval: float = 0.4) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.read: list[float] = []
        self.write: list[float] = []
        self._stop = threading.Event()

    def run(self) -> None:
        last = time.time()
        io = psutil.disk_io_counters()
        lr, lw = io.read_bytes, io.write_bytes
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            now = time.time()
            dt = max(1e-6, now - last)
            last = now
            io = psutil.disk_io_counters()
            self.read.append((io.read_bytes - lr) / dt / (1 << 20))
            self.write.append((io.write_bytes - lw) / dt / (1 << 20))
            lr, lw = io.read_bytes, io.write_bytes

    def stop(self) -> None:
        self._stop.set()

    def summary(self) -> dict[str, float]:
        def avg(v: list[float]) -> float:
            return sum(v) / len(v) if v else 0.0

        return {"read_avg": avg(self.read), "write_avg": avg(self.write),
                "read_max": max(self.read) if self.read else 0.0,
                "write_max": max(self.write) if self.write else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intensity", default=None,
                    choices=["low", "medium", "high"])
    ap.add_argument("--no-size", action="store_true")
    ap.add_argument("--whole", action="store_true",
                    help="同时报告全系统 CPU / 磁盘占用（含拉起的子进程）")
    args = ap.parse_args()

    if args.intensity:
        core.update_config(scan_intensity=args.intensity)
    intensity = core.scan_intensity()
    print(f"性能档位: {intensity}   逻辑核心: {psutil.cpu_count()}   "
          f"数据目录: {core.data_dir()}")

    base = idle_baseline(3.0) if args.whole else {}
    if args.whole:
        print(f"空闲基线：CPU {base['cpu_avg']:.1f}%   "
              f"全盘读 {base['disk_read_mbps']:.2f} MB/s   写 "
              f"{base['disk_write_mbps']:.2f} MB/s")

    sampler = Sampler(os.getpid())
    disk = DiskSampler() if args.whole else None
    sampler.start()
    if disk:
        disk.start()
    t0 = time.time()
    findings = scanner.scan(include_disputed=True,
                            compute_size=not args.no_size)
    elapsed = time.time() - t0
    sampler.stop()
    if disk:
        disk.stop()
    time.sleep(0.5)

    s = sampler.summary()
    print(f"\n扫描耗时: {elapsed:.2f}s   命中家族: {len(findings)}")
    if s:
        print("\n----- CPU（任务管理器口径，整机百分比） -----")
        print(f"  平均 {s['cpu_total_avg']:.2f}%   "
              f"P50 {s['cpu_total_p50']:.2f}%   "
              f"P95 {s['cpu_total_p95']:.2f}%   峰值 {s['cpu_total_max']:.2f}%")
        print(f"  （等效占满 {s['cpu_cores_avg']:.2f} 个核，峰值 "
              f"{s['cpu_cores_max']:.2f} 个核 / 共 {int(s['logical_cores'])} 个）")
        print("\n----- 磁盘（本进程） -----")
        print(f"  读  平均 {s['read_avg_mbps']:.2f} MB/s   "
              f"P95 {s['read_p95_mbps']:.2f}   "
              f"峰值 {s['read_max_mbps']:.2f} MB/s")
        print(f"  写  平均 {s['write_avg_mbps']:.2f} MB/s   "
              f"P95 {s['write_p95_mbps']:.2f}   "
              f"峰值 {s['write_max_mbps']:.2f} MB/s")

        ok_cpu = s["cpu_total_avg"] < 5.0
        ok_cpu_p95 = s["cpu_total_p95"] < 5.0
        print(f"\nCPU 平均 < 5%: {'达标' if ok_cpu else '未达标'}"
              f"   P95 < 5%: {'达标' if ok_cpu_p95 else '未达标'}")
    if args.whole and disk:
        d = disk.summary()
        print("\n----- 全盘读写（含系统其他活动） -----")
        print(f"  读  平均 {d['read_avg']:.2f} MB/s   峰值 {d['read_max']:.2f}")
        print(f"  写  平均 {d['write_avg']:.2f} MB/s   峰值 {d['write_max']:.2f}")
        if s:
            print(f"\n全系统 CPU（含子进程）：平均 "
                  f"{s['system_cpu_avg']:.1f}%   峰值 {s['system_cpu_max']:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
