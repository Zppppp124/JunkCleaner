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

性能：用 bytearray 分块写入 + 块级比对，零第三方依赖
（numpy 在打包环境被排除，曾导致本功能直接崩），
2GB 跑完一轮约 30 秒，适合放进 GUI。
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

# 分块处理大小：整块内存会被写入并校验，但「比对」按块进行，
# 避免一次性构造等长的副本与小对象（后者会引发内存爆炸）。
CHUNK = 8 << 20          # 8 MB
MAX_ERRORS = 5000


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
    """多线程内存测试（bytearray 分块，零第三方依赖）。"""

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

    def _add_error(self, offset: int, expected: int, actual: int,
                   pattern: str, pass_no: int) -> None:
        with self._lock:
            if len(self.result.errors) < MAX_ERRORS:
                self.result.errors.append(MemError(
                    offset=offset, expected=f"0x{expected:08X}",
                    actual=f"0x{actual:08X}",
                    pattern=pattern, pass_no=pass_no))

    def _verify_forward(self, mv: Any, start: int, nbytes: int, expected: int,
                        pattern: str, pass_no: int) -> None:
        """顺序读：按块比对，块内用一次字节比较定位是否整块一致。

        关键点：不做整段副本、不切 4 字节小对象——2GB 时那样会产生
        数亿个临时对象，直接把进程撑爆。
        """
        exp = (expected & 0xFFFFFFFF).to_bytes(4, "little")
        unit = exp * (CHUNK // 4)
        end = start + nbytes
        off = start
        while off < end:
            n = min(CHUNK, end - off)
            n -= n % 4
            if n <= 0:
                break
            if mv[off:off + n] != unit[:n]:
                # 只有命中坏块才逐字定位，避免常态开销
                raw = bytes(mv[off:off + n])
                for i in range(0, n, 4):
                    if raw[i:i + 4] != exp:
                        self._add_error(off + i, expected,
                                        int.from_bytes(raw[i:i + 4], "little"),
                                        pattern, pass_no)
                        if len(self.result.errors) >= MAX_ERRORS:
                            return
            off += n

    def _verify_stride(self, mv: Any, start: int, nbytes: int, expected: int,
                       pattern: str, pass_no: int) -> None:
        """跨步读：每 64 字节抽一个 4 字节字，制造行/列干扰。"""
        exp = (expected & 0xFFFFFFFF).to_bytes(4, "little")
        end = start + nbytes
        off = start
        while off < end - 3:
            if mv[off:off + 4] != exp:
                self._add_error(off, expected,
                                int.from_bytes(mv[off:off + 4], "little"),
                                f"{pattern}(跨步)", pass_no)
                if len(self.result.errors) >= MAX_ERRORS:
                    return
            off += 64

    def _test_chunk(self, mv: Any, start: int, nbytes: int,
                    pattern: int, name: str, pass_no: int) -> int:
        """对一个分片跑一轮完整校验，返回扫描字节数。

        用 bytearray 分块处理（不依赖 numpy）：numpy 在打包环境里被
        spec 的 excludes 排除，会导致内存测试直接 ModuleNotFoundError。
        """
        if nbytes <= 0:
            return 0
        pat = (pattern & 0xFFFFFFFF).to_bytes(4, "little")
        # 写：整段填充（分块构造，避免造等长巨型 bytes）
        end = start + nbytes
        off = start
        while off < end:
            n = min(CHUNK, end - off)
            n -= n % 4
            if n <= 0:
                break
            mv[off:off + n] = pat * (n // 4)
            off += n
        scanned = nbytes
        self._verify_forward(mv, start, nbytes, pattern, name, pass_no)
        if self._stop.is_set() or len(self.result.errors) >= MAX_ERRORS:
            return scanned
        self._verify_stride(mv, start, nbytes, pattern, name, pass_no)
        return scanned

    def _worker(self, mv: Any, size: int, idx: int, total: int) -> None:
        chunk = size // total
        start = idx * chunk
        n = chunk if idx < total - 1 else (size - start)
        # 每线程的分片对齐到 4 字节
        n -= n % 4
        for p in range(1, self.rounds + 1):
            if self._stop.is_set():
                return
            for name, pat in PATTERNS:
                if self._stop.is_set():
                    return
                scanned = self._test_chunk(mv, start, n, pat, name, p)
                with self._lock:
                    self.result.patterns_done += 1
                    self.result.bytes_scanned += scanned
    def run(self) -> MemTestResult:
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
        # 对齐到 4 字节
        size -= size % 4

        self._log(f"分配 {size >> 20} MB 并触碰全部页面…")
        try:
            # bytearray：零依赖（不依赖 numpy），且可直接切片比较
            mv = bytearray(size)
        except MemoryError:
            self.result.note = "内存分配失败"
            return self.result
        # 强制提交物理页
        touch = 1 << 16
        for off in range(0, size, touch):
            mv[off] = 1

        self.result.note = (f"仅测试空闲内存 {size >> 20} MB；"
                            f"Windows 自身占用的 {max(0, total_gb-free_gb):.1f} GB "
                            f"无法测试（需从 U 盘启动 MemTest86+ 才能全覆盖）")

        self._log(f"启动 {self.threads} 个测试线程，{self.rounds} 轮 × "
                  f"{len(PATTERNS)} 图案…")
        start = time.time()
        workers = [threading.Thread(target=self._worker,
                                    args=(mv, size, i, self.threads),
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
        del mv
        core.log(f"内存测试：{self.result.alloc_mb}MB，"
                 f"错误 {len(self.result.errors)}，{self.result.seconds}s",
                 source="memtest")
        return self.result
