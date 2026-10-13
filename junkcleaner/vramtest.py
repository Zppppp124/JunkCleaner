"""显存稳定性测试（内嵌 memtest_vulkan）。

memtest_vulkan 是 GpuZelenograd 开源的显存测试工具（zlib 许可），
通过 Vulkan compute 反复写入并校验显存内容，能发现显存超频/老化
导致的位错误——这类错误往往表现为游戏花屏，但普通满载压测测不到。

许可证与来源见 assets/LICENSE-memtest_vulkan.txt。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import core

EXE_NAME = "memtest_vulkan.exe"

# 输出中的关键标记（来自官方 v0.5.0 二进制内嵌字符串）
_PASS_MARK = "testing PASSed"
_FAIL_MARKS = (
    "ERRORS FOUND",
    "testing finished",
    "INIT OR FIRST testing failed",
    "runtime error occured",
)
_ERROR_LINE = re.compile(r"Error found\. Mode .* total errors", re.I)
_PROGRESS = re.compile(
    r"^\s*(\d+)\s+iteration\.\s+Passed\s+([\d.]+)\s+seconds\s+"
    r"written:\s*([\d.]+)GB\s+([\d.]+)GB/sec\s+checked:\s*([\d.]+)GB",
    re.I)
_DEVICE = re.compile(r"^\s*\d+:\s+Bus=(0x[0-9A-Fa-f:]+).*?\s+(\d+)GB\s+(.+?)\s*$")


def _asset_path() -> Path | None:
    """定位内嵌（或源码目录）的 memtest_vulkan.exe。"""
    base = getattr(sys, "_MEIPASS", None)
    roots = []
    if base:
        roots.append(Path(base) / "junkcleaner" / "assets")
    roots.append(Path(__file__).resolve().parent / "assets")
    for r in roots:
        p = r / EXE_NAME
        if p.exists():
            return p
    return None


def available() -> bool:
    return _asset_path() is not None


def _extract_dir() -> Path:
    """可写目录：内嵌资源在只读临时目录，需复制出来再运行。"""
    d = core.data_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare() -> Path | None:
    """把内嵌的 exe 复制到可写目录并返回路径。"""
    src = _asset_path()
    if src is None:
        return None
    dst = _extract_dir() / EXE_NAME
    try:
        if (not dst.exists()) or dst.stat().st_size != src.stat().st_size:
            import shutil
            shutil.copy2(src, dst)
        return dst
    except OSError as exc:
        core.log(f"释放 memtest_vulkan 失败：{exc}", level="ERROR",
                 source="vramtest")
        return None


class VramTest:
    """运行 memtest_vulkan，实时解析输出。

    运行方式：以子进程启动，stdout 重定向到临时日志文件，
    由调用方轮询 progress_raw() 取最新输出。
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.log_path = _extract_dir() / "memtest_vulkan_output.log"
        self._fh = None
        self.device = ""
        self.errors: list[str] = []
        self.iterations = 0
        self.written_gb = 0.0
        self.checked_gb = 0.0
        self.speed_gb_s = 0.0
        self.finished = False
        self.passed: bool | None = None
        self._stop = False

    # ---------------- 生命周期 ----------------
    def start(self) -> dict[str, Any]:
        exe = prepare()
        if exe is None:
            return {"ok": False, "error": "未找到内嵌的 memtest_vulkan.exe"}
        try:
            self._fh = open(self.log_path, "wb")
        except OSError as exc:
            return {"ok": False, "error": f"无法创建日志文件：{exc}"}
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                [str(exe)], stdout=self._fh, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, cwd=str(exe.parent),
                creationflags=flags)
        except Exception as exc:  # noqa: BLE001
            self._close()
            return {"ok": False, "error": f"启动失败：{exc}"}
        core.log("显存测试已启动（memtest_vulkan）", source="vramtest")
        return {"ok": True, "path": str(exe)}

    def _close(self) -> None:
        try:
            if self._fh and not self._fh.closed:
                self._fh.flush()
                self._fh.close()
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> None:
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._close()

    @property
    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    # ---------------- 输出解析 ----------------
    def raw_output(self) -> str:
        try:
            if self._fh and not self._fh.closed:
                self._fh.flush()
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def poll(self) -> dict[str, Any]:
        """解析最新输出，更新状态并返回快照。"""
        text = self.raw_output()
        for line in text.splitlines():
            m = _DEVICE.match(line)
            if m and not self.device:
                self.device = f"{m.group(3).strip()} ({m.group(2)}GB)"
            if _ERROR_LINE.search(line):
                if line.strip() not in self.errors:
                    self.errors.append(line.strip())
            m2 = _PROGRESS.match(line)
            if m2:
                self.iterations = int(m2.group(1))
                self.written_gb = float(m2.group(3))
                self.speed_gb_s = float(m2.group(4))
                self.checked_gb = float(m2.group(5))
        if not self.finished:
            if _PASS_MARK in text:
                self.passed = True
                self.finished = True
            elif any(k in text for k in _FAIL_MARKS):
                self.passed = False
                self.finished = True
        # 进程已退出但没有明确结论，按结果判断
        if not self.running and self.proc is not None and not self.finished:
            if _PASS_MARK in text:
                self.passed = True
            elif self.errors or "ERR" in text.upper():
                self.passed = False
            self.finished = True
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "finished": self.finished,
            "passed": self.passed,
            "device": self.device,
            "iterations": self.iterations,
            "written_gb": round(self.written_gb, 1),
            "checked_gb": round(self.checked_gb, 1),
            "speed_gb_s": round(self.speed_gb_s, 1),
            "errors": list(self.errors[:10]),
            "error_count": len(self.errors),
            "stopped_by_user": self._stop,
        }

    def summary(self) -> dict[str, Any]:
        snap = self.snapshot()
        if snap["passed"] is True:
            snap["verdict"] = "未发现显存错误"
        elif snap["passed"] is False:
            snap["verdict"] = "检出显存错误"
        elif snap["stopped_by_user"]:
            snap["verdict"] = "已手动停止（未跑完，结论不完整）"
        else:
            snap["verdict"] = "尚未得出结果"
        core.log(f"显存测试结束：{snap['verdict']}"
                 f"（迭代 {snap['iterations']}，校验 {snap['checked_gb']}GB）",
                 source="vramtest")
        return snap


def run_blocking(seconds: int = 360,
                 progress: Callable[[str], None] | None = None
                 ) -> dict[str, Any]:
    """同步跑一段显存测试（供命令行/自检使用）。"""
    t = VramTest()
    r = t.start()
    if not r.get("ok"):
        return r
    start = time.time()
    try:
        while time.time() - start < seconds:
            snap = t.poll()
            if progress:
                try:
                    progress(f"迭代 {snap['iterations']}　"
                             f"已校验 {snap['checked_gb']}GB　"
                             f"{snap['speed_gb_s']}GB/s")
                except Exception:  # noqa: BLE001
                    pass
            if snap["finished"]:
                break
            time.sleep(2)
    finally:
        if t.running:
            t.stop()
    return t.summary()
