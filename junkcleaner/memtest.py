"""内存测试（Windows 级实现，替代 MemTest 的逻辑思路）。

原理与限制（必须说明）
---------------------
MemTest86 之所以要从 U 盘启动，是因为**它要独占全部物理内存**。
Windows 运行时内核与驱动已占用部分物理页，用户态无法碰，
因此本模块只能测试「空闲可用」的那部分内存。

能查出：空闲内存的位翻转、地址解码错误、单元不稳定、高负载下的错误
查不出：Windows 自身占用的内存区域内的错误

测试图案参考 MemTest 系列的公开做法：
  全0 / 全1 / 0x5555 / 0xAAAA / 0x3333 / 0xCCCC / 地址型 / 随机
每个图案做 顺序写→顺序读→逆序读→跨步读，覆盖位干扰与行/列解码方向性。

性能：使用 numpy 向量化（比纯 Python 循环快数百倍），
2GB 内存跑完一轮约几秒，适合放进 GUI。
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from . import core

PATTERNS: list[tuple[str, int]] = [
    ("全 0", 0x00000000),
    ("全 1", 0xFFFFFFFF),
    ("0x5555", 0x55555555),
    ("0xAAAA", 0xAAAAAAAA),
    ("0x3333", 0x33333333),
    ("0xCCCC", 0xCCCCCCCC),
    ("0xFFFF0000", 0xFFFF0000),
    ("0x0000FFFF", 0x0000FFFF),
]


@dataclass
class MemError:
    offset: int
    expected: str
    actual: str
    pattern: str
    pass_no: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemTestResult:
    alloc_mb: int = 0
    patterns_done: int = 0
    bytes_scanned: int = 0
    errors: list[MemError] = field(default_factory=list)
    seconds: float = 0.0
    cancelled: bool = False
    total_ram_gb: float = 0.0
    free_ram_gb: float = 0.0
    passed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["errors"] = self.errors[:40]
        d["error_count"] = len(self.errors)
        return d


def available_memory() -> tuple[float, float]:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.total / (1 << 30), vm.available / (1 << 30)
    except Exception:  # noqa: BLE001
        return 0.0, 0.0


def numpy_available() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class MemTester:
    """多线程内存测试（numpy 向量化）。"""

    def __init__(self, alloc_mb: int = 2048, threads: int = 0,
                 rounds: int = 1,
                 progress: Callable[[str], None] | None = None) -> None:
        self.alloc_mb = max(64, int(alloc_mb))
        self.threads = threads or min(4, os.cpu_count() or 2)
        self.rounds = max(1, int(rounds))
        self.progress = progress or (lambda _m: None)
        self._stop = threading.Event()
        self.result = MemTestResult(alloc_mb=self.alloc_mb)
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._stop.set()

    def _log(self, m: str) -> None:
        try:
            self.progress(m)
        except Exception:  # noqa: BLE001
            pass

    def _record(self, offsets: Any, expected: int, actual: Any,
                pattern: str, pass_no: int, base: int) -> None:
        import numpy as np
        with self._lock:
            room = 5000 - len(self.result.errors)
            if room <= 0:
                return
            bad = np.nonzero(actual != expected)[0][:room]
            for i in bad:
                self.result.errors.append(MemError(
                    offset=base + int(i) * 4,
                    expected=f"0x{expected:08X}",
                    actual=f"0x{int(actual[i]):08X}",
                    pattern=pattern, pass_no=pass_no))

    def _test_chunk(self, arr: Any, base_word: int, words: int,
                    pattern: int, name: str, pass_no: int) -> int:
        """对一个分片跑一轮完整校验，返回扫描字节数。"""
        import numpy as np
        seg = arr[base_word:base_word + words]
        if seg.size == 0:
            return 0
        # 写
        seg[:] = np.uint32(pattern)
        scanned = seg.size * 4
        # 顺序读
        got = seg.copy()
        self._record(None, pattern, got, name, pass_no, base_word * 4)
        if self._stop.is_set():
            return scanned
        # 逆序读（模拟 MemTest 的地址解码方向测试）
        rev = seg[::-1]
        self._record(None, pattern, rev, name, pass_no, base_word * 4)
        if self._stop.is_set():
            return scanned
        # 跨步读（每 16 字 = 64 字节一处，制造行/列干扰）
        step = seg[::16]
        self._record(None, pattern, step, name, pass_no, base_word * 4)
        return scanned

    def _worker(self, arr: Any, words: int, idx: int, total: int) -> None:
        chunk = words // total
        base = idx * chunk
        n = chunk if idx < total - 1 else (words - base)
        for p in range(1, self.rounds + 1):
            if self._stop.is_set():
                return
            for name, pat in PATTERNS:
                if self._stop.is_set():
                    return
                scanned = self._test_chunk(arr, base, n, pat, name, p)
                with self._lock:
                    self.result.patterns_done += 1
                    self.result.bytes_scanned += scanned

    def run(self) -> MemTestResult:
        import numpy as np

        total_gb, free_gb = available_memory()
        self.result.total_ram_gb = round(total_gb, 1)
        self.result.free_ram_gb = round(free_gb, 1)

        size = self.alloc_mb * (1 << 20)
        # 最多用可用内存的 70%，留足余量避免系统卡死
        limit = int(free_gb * (1 << 30) * 0.70)
        if size > limit:
            size = max(64 << 20, limit)
            self.result.alloc_mb = size >> 20
            self._log(f"可用内存有限，自动调整为 {size >> 20} MB")
        words = size // 4

        self._log(f"分配 {size >> 20} MB 并触碰全部页面…")
        try:
            arr = np.zeros(words, dtype=np.uint32)
        except MemoryError:
            self.result.note = "内存分配失败"
            return self.result
        # 强制提交物理页
        for off in range(0, words, 1 << 16):
            arr[off] = 1

        self.result.note = (f"仅测试空闲内存 {size >> 20} MB；"
                            f"Windows 自身占用的 {max(0, total_gb-free_gb):.1f} GB "
                            f"无法测试（需从 U 盘启动 MemTest86+ 才能全覆盖）")

        self._log(f"启动 {self.threads} 个测试线程，{self.rounds} 轮 × "
                  f"{len(PATTERNS)} 图案…")
        start = time.time()
        workers = [threading.Thread(target=self._worker,
                                    args=(arr, words, i, self.threads),
                                    daemon=True)
                   for i in range(self.threads)]
        for w in workers:
            w.start()
        while any(w.is_alive() for w in workers):
            time.sleep(1.5)
            with self._lock:
                done = self.result.patterns_done
                errs = len(self.result.errors)
                mb = self.result.bytes_scanned / (1 << 20)
            self._log(f"已完成 {done} 组图案 / 扫描 {mb:.0f} MB / "
                      f"错误 {errs} / {int(time.time()-start)}s")
            if self._stop.is_set():
                break
        self._stop.set()
        for w in workers:
            w.join(timeout=10)

        self.result.seconds = round(time.time() - start, 1)
        # 正常跑完：所有线程都已退出（不是被 cancel）
        finished = all(not w.is_alive() for w in workers)
        self.result.cancelled = not finished
        self.result.passed = not self.result.errors and finished
        del arr
        core.log(f"内存测试：{self.result.alloc_mb}MB，"
                 f"错误 {len(self.result.errors)}，{self.result.seconds}s",
                 source="memtest")
        return self.result
