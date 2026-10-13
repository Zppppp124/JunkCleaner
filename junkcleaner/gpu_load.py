"""GPU 压力测试：用 PyTorch CUDA 让显卡真正满载。

为什么必须跑负载
----------------
降压不稳的表现是「高负载下掉频/驱动重置」。如果只是空闲着看频率，
即使电压低到不可用也看不出问题。所以要真的把核心算满。

负载方式：连续做大规模 FP16/FP32 矩阵乘法（张量核心 + FP32 双路），
同时周期性做显存搬运，覆盖核心与显存两条供电路径。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


def cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def stress_backend() -> dict[str, Any]:
    """返回可用的满载后端信息。

    打包版没有内置 PyTorch，必须依赖系统 Python；因此不能只用
    cuda_available() 判断，否则会误报“CUDA 不可用”而完全不跑负载。
    """
    if cuda_available():
        try:
            import torch
            return {"ok": True, "mode": "builtin",
                    "device": torch.cuda.get_device_name(0)}
        except Exception:  # noqa: BLE001
            return {"ok": True, "mode": "builtin", "device": ""}
    py = system_python_with_torch()
    if py:
        return {"ok": True, "mode": "external", "python": py}
    return {"ok": False, "mode": "none",
            "error": "未找到带 CUDA 的 PyTorch（内置或系统 Python 都没有）"}


def stress_available() -> bool:
    return bool(stress_backend().get("ok"))


def system_python_with_torch() -> str:
    """找一个装了 torch+CUDA 的系统 Python。

    打包进 exe 会带上 2GB+ 的 PyTorch，不现实；因此打包后改为
    调用系统 Python 跑 CUDA 负载。
    """
    local = os.environ.get("LOCALAPPDATA", "")
    candidates: list[str] = []
    for ver in ("313", "312", "311", "310"):
        if local:
            candidates.append(
                rf"{local}\Programs\Python\Python{ver}\python.exe")
    for c in ("python.exe", "python3.exe"):
        p = shutil.which(c)
        if p:
            candidates.append(p)
    probe = ("import torch,sys;"
             "sys.exit(0 if torch.cuda.is_available() else 1)")
    for exe in candidates:
        if not Path(exe).exists():
            continue
        try:
            p = subprocess.run([exe, "-c", probe], capture_output=True,
                               timeout=90,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            if p.returncode == 0:
                return exe
        except Exception:  # noqa: BLE001
            continue
    return ""


HELPER = r'''
import sys, time
import torch

# argv: duration  transient(0/1)  high_ms  low_ms
duration = float(sys.argv[1])
transient = bool(int(sys.argv[2])) if len(sys.argv) > 2 else False
high_ms = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
low_ms = float(sys.argv[4]) if len(sys.argv) > 4 else 60.0

torch.cuda.set_device(0)
n = 4096
dt = torch.float16
a = torch.randn(n, n, device="cuda", dtype=dt) * 0.1
b = torch.randn(n, n, device="cuda", dtype=dt) * 0.1
host = torch.empty(1024, 1024, dtype=dt)
deadline = time.time() + duration
bad = 0

def heavy():
    global a
    for _ in range(8):
        a = torch.relu(a @ b) * 0.001
        c = torch.matmul(a, b)
    host.copy_(c[:1024, :1024], non_blocking=True)
    torch.cuda.synchronize()
    return c

def validate(c):
    """降压不稳的典型表现是「时钟正常但算错」——这类静默数据损坏
    不会抛 CUDA 异常，只能靠校验结果发现，否则会误判为稳定。"""
    if not torch.isfinite(c).all().item():
        return "CORRUPT:nonfinite"
    peak = c.abs().max().item()
    if peak != peak or peak > 1e6:
        return "CORRUPT:peak"
    return ""

while time.time() < deadline:
    c = heavy()
    msg = validate(c)
    if msg:
        bad += 1
        print(msg, flush=True)
        break
    if transient:
        # 瞬态负载：在满载与轻载之间反复跳变，制造电流突变（dv/dt）。
        # 游戏卡顿/花屏多由这种瞬态压降引起，恒定满载测不出来。
        torch.cuda.synchronize()
        time.sleep(low_ms / 1000.0)

print("OK" if bad == 0 else "BAD", flush=True)
print("DONE")
'''


class ExternalStress:
    """在独立 Python 进程里跑 CUDA 负载（打包后的 exe 用）。"""

    def __init__(self, seconds: int, transient: bool = False,
                 high_ms: float = 120.0, low_ms: float = 60.0) -> None:
        self.seconds = int(seconds)
        self.transient = bool(transient)
        self.high_ms = float(high_ms)
        self.low_ms = float(low_ms)
        self.proc: subprocess.Popen | None = None
        self.python = system_python_with_torch()
        # 把子进程输出写到临时文件，用于读取「静默数据损坏」标记。
        # 用文件而不是管道，避免父进程不读取时管道写满导致子进程阻塞。
        self.log_path = Path(tempfile.gettempdir()) / (
            f"jc_gpu_stress_{os.getpid()}_{int(time.time())}.log")
        self._fh = None

    def start(self) -> bool:
        if not self.python:
            return False
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            self._fh = open(self.log_path, "wb")
            self.proc = subprocess.Popen(
                [self.python, "-c", HELPER, str(self.seconds),
                 "1" if self.transient else "0",
                 str(self.high_ms), str(self.low_ms)],
                stdout=self._fh, stderr=subprocess.STDOUT,
                creationflags=flags)
            return True
        except Exception:  # noqa: BLE001
            self._close_fh()
            return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._close_fh()

    def _close_fh(self) -> None:
        try:
            if self._fh and not self._fh.closed:
                self._fh.flush()
                self._fh.close()
        except Exception:  # noqa: BLE001
            pass

    def output(self) -> str:
        """读取子进程输出（含 CORRUPT / OK 标记）。"""
        try:
            if self._fh and not self._fh.closed:
                self._fh.flush()
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def corruption(self) -> str:
        """若负载期间检出数值损坏，返回原因；否则返回空串。"""
        text = self.output()
        for line in text.splitlines():
            if line.startswith("CORRUPT"):
                return line.strip()
        if "BAD" in text.split():
            return "负载期间检出计算结果损坏（花屏/静默数据错误的典型表现）"
        return ""

    @property
    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    @property
    def returncode(self) -> int | None:
        return self.proc.poll() if self.proc else None


def device_name() -> str:
    try:
        import torch
        return torch.cuda.get_device_name(0) if torch.cuda.is_available() else ""
    except Exception:  # noqa: BLE001
        return ""


class GpuStress:
    """在后台线程持续给 GPU 加载。"""

    def __init__(self, size: int = 4096, use_fp16: bool = True,
                 transient: bool = False,
                 high_ms: float = 120.0, low_ms: float = 60.0) -> None:
        self.size = size
        self.use_fp16 = use_fp16
        self.transient = bool(transient)
        self.high_ms = float(high_ms)
        self.low_ms = float(low_ms)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._external: ExternalStress | None = None
        self.errors: list[str] = []
        self.iterations = 0
        self.start_time = 0.0
        # 打包环境没有 torch：改用外部 Python 进程
        self._use_external = not cuda_available()

    def _loop(self) -> None:
        try:
            import torch
            torch.cuda.set_device(0)
            dt = torch.float16 if self.use_fp16 else torch.float32
            n = self.size
            a = torch.randn(n, n, device="cuda", dtype=dt) * 0.1
            b = torch.randn(n, n, device="cuda", dtype=dt) * 0.1
            # 保留一份结果用于跨设备搬运，覆盖显存带宽
            host = torch.empty(1024, 1024, dtype=dt)
            while not self._stop.is_set():
                for _ in range(8):
                    a = torch.relu(a @ b) * 0.001
                    c = torch.matmul(a, b)
                # 显存搬运（触发显存控制器与供电）
                host.copy_(c[:1024, :1024], non_blocking=True)
                torch.cuda.synchronize()
                self.iterations += 1
                # 静默数据损坏检测：时钟正常但算错，必须主动校验
                if not bool(torch.isfinite(c).all().item()):
                    self.errors.append(
                        "检出计算结果损坏（非有限值）——降压不稳的典型表现")
                    break
                a = torch.randn(n, n, device="cuda", dtype=dt) * 0.1
        except Exception as exc:  # noqa: BLE001
            self.errors.append(str(exc))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.start_time = time.time()
        if self._use_external:
            ext = ExternalStress(seconds=3600, transient=self.transient,
                                 high_ms=self.high_ms, low_ms=self.low_ms)
            if ext.start():
                self._external = ext
                # 确认外部 CUDA 进程没有立刻退出（缺 DLL / 驱动不匹配
                # 都会导致瞬间退出，若不检查就会看起来“没有占用”）。
                time.sleep(1.5)
                if not ext.alive:
                    self.errors.append(
                        f"CUDA 负载进程启动后立即退出（rc={ext.returncode}）")
                    self._external = None
                return
            self.errors.append("未找到带 CUDA 的 Python（torch 不可用）")
            return
        self._thread = threading.Thread(target=self._loop, name="GpuStress",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._external:
            self._external.stop()
            self._external = None
        if self._thread:
            self._thread.join(timeout=10)

    @property
    def running(self) -> bool:
        if self._external:
            return self._external.alive
        return bool(self._thread and self._thread.is_alive())

    def summary(self) -> dict[str, Any]:
        corruption = ""
        if self._external is not None:
            try:
                corruption = self._external.corruption()
            except Exception:  # noqa: BLE001
                corruption = ""
        errors = list(self.errors[:3])
        if corruption:
            errors.append(corruption)
        return {"iterations": self.iterations,
                "errors": errors,
                "corruption": corruption,
                "seconds": time.time() - self.start_time if self.start_time else 0}


def load_test(seconds: int, size: int = 4096,
              progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """跑一段满载压力测试，返回是否出现 CUDA 错误。"""
    s = GpuStress(size=size)
    s.start()
    start = time.time()
    while time.time() - start < seconds:
        if progress:
            try:
                progress(f"满载 {int(time.time()-start)}/{seconds}s "
                         f"（{s.iterations} 轮）")
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)
        if s.errors:
            break
    s.stop()
    r = s.summary()
    r["ok"] = not r["errors"]
    return r
