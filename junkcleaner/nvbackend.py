"""NVAPI 降压后端（不依赖 MSI Afterburner）。

MSI Afterburner 是专有软件，其许可不允许随第三方程序再分发，
且它运行时不重读被外部修改的 Profile，导致「写完曲线不生效」。

本模块改为调用开源 CLI 工具 simple-nvidia-undervolt（MIT 许可）：
  * 直接通过 NVAPI 的 Pstates20 接口读写 V/F 曲线，无需 Afterburner
  * 没有后台进程、没有内核驱动、无遥测
  * 附带真实核心电压读取（Afterburner/ nvidia-smi 都读不到）

工具既可直接使用（用户自行安装），也可内嵌在本程序资源里。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from . import core

EXE_NAME = "simple-nvidia-undervolt.exe"
# 工具自身安装的位置（其 install 子命令会把程序放这里）
INSTALL_DIR = Path(r"C:\Program Files\simple-nvidia-undervolt")
INSTALLED_EXE = INSTALL_DIR / EXE_NAME
# 该工具在数据目录下保存持久化配置
PERSISTED = INSTALL_DIR / "data" / "persisted-tuning.json"

CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------
# 定位可执行文件
# --------------------------------------------------------------------------
def _asset_path() -> Path | None:
    """内嵌资源中的工具（打包后位于 _MEIPASS）。"""
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


def extract_dir() -> Path:
    d = core.data_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


_cached_exe: Path | None = None


def exe_path() -> Path | None:
    """返回可用的工具路径（优先内嵌副本，其次系统已安装的）。

    结果会缓存：本函数被高频调用（每次状态刷新），
    每次都 stat/copy 检查会带来无谓开销。
    """
    global _cached_exe
    if _cached_exe is not None and _cached_exe.exists():
        return _cached_exe
    src = _asset_path()
    if src is not None:
        dst = extract_dir() / EXE_NAME
        try:
            if (not dst.exists()) or dst.stat().st_size != src.stat().st_size:
                shutil.copy2(src, dst)
            _cached_exe = dst
            return dst
        except OSError as exc:
            core.log(f"释放 {EXE_NAME} 失败：{exc}", level="WARN",
                     source="nvbackend")
    if INSTALLED_EXE.exists():
        _cached_exe = INSTALLED_EXE
        return INSTALLED_EXE
    found = shutil.which("simple-nvidia-undervolt")
    _cached_exe = Path(found) if found else None
    return _cached_exe


def available() -> bool:
    return exe_path() is not None


# --------------------------------------------------------------------------
# 调用封装
# --------------------------------------------------------------------------
def _run(args: list[str], timeout: int = 180) -> dict[str, Any]:
    """运行工具，返回 {ok, rc, out}。

    注意：'status' / 'watch' / 诊断命令本身只读且无需提权；
    调参类命令需要管理员，工具自己会弹 UAC（本程序通常已是管理员）。
    """
    exe = exe_path()
    if exe is None:
        return {"ok": False, "rc": -1, "out": "",
                "error": f"未找到 {EXE_NAME}"}
    cmd = [str(exe), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": 124, "out": "", "error": "执行超时"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "rc": -1, "out": "", "error": str(exc)}
    out = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")
    return {"ok": p.returncode == 0, "rc": p.returncode, "out": out.strip()}


_VOLT_LINE = re.compile(r"^\s*(\d+)\s*mV\s*->\s*(\d+)\s*MHz", re.M)
# 工具输出形如 "operating point 955 mV / ~2843 MHz"（~ 可能紧跟数字）
_OP_POINT = re.compile(
    r"operating\s+point\s+(\d+)\s*mV\s*/\s*~?\s*(\d+)\s*MHz", re.I)
_OFFSET_SUM = re.compile(r"Core curve offset:\s*(.+)")


def status() -> dict[str, Any]:
    """读取当前调参状态（只读，不需要管理员）。"""
    r = _run(["status"], timeout=60)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or r.get("out", "")[:200]}
    text = r["out"]
    info: dict[str, Any] = {"ok": True, "raw": text}
    m = _OP_POINT.search(text)
    if m:
        info["mv"] = int(m.group(1))
        info["mhz"] = int(m.group(2))
    m = _OFFSET_SUM.search(text)
    if m:
        info["offset_summary"] = m.group(1).strip()
    info["is_stock"] = "Core curve offset: stock" in text
    info["persists"] = "Re-applies at logon: yes" in text
    return info


def read_voltage() -> dict[str, Any]:
    """读一次真实核心电压/频率/温度/功耗（只读）。"""
    r = _run(["voltage"], timeout=60)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or r.get("out", "")[:200]}
    text = r["out"]
    mv = re.search(r"(\d+)\s*mV", text)
    mhz = re.search(r"(\d+)\s*MHz", text)
    temp = re.search(r"(\d+)\s*C", text)
    power = re.search(r"([\d.]+)\s*W", text)
    out: dict[str, Any] = {"ok": True, "raw": text}
    if mv:
        out["voltage_mv"] = int(mv.group(1))
    if mhz:
        out["clock_mhz"] = int(mhz.group(1))
    if temp:
        out["temp_c"] = int(temp.group(1))
    if power:
        out["power_w"] = float(power.group(1))
    return out


def read_curve() -> dict[str, Any]:
    """读取当前生效的 V/F 曲线（电压 -> 频率）。"""
    r = _run(["curve"], timeout=90)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or r.get("out", "")[:200]}
    points = [(int(m.group(1)), int(m.group(2)))
              for m in _VOLT_LINE.finditer(r["out"])]
    return {"ok": True, "points": points, "count": len(points),
            "raw": r["out"]}


def read_live() -> dict[str, Any]:
    """一次调用同时拿到「实时读数 + 应用状态」。

    为什么合并：每次调用都要启动一个子进程（约 40ms）。UI 每秒刷新时
    若分别调用 read_voltage / status / read_curve，就是 3 次进程往返。
    这里用一次 `status` + 一次 `voltage`（共 2 次）覆盖界面所需的全部
    信息，曲线信息改为按需读取。
    """
    out: dict[str, Any] = {"ok": False}
    v = read_voltage()
    if v.get("ok"):
        out.update({
            "ok": True,
            "clock_mhz": v.get("clock_mhz", 0),
            "voltage_mv": v.get("voltage_mv", 0),
            "temp_c": v.get("temp_c", 0),
            "power_w": v.get("power_w", 0),
        })
    st = status()
    if st.get("ok"):
        out["applied_mv"] = st.get("mv")
        out["applied_mhz"] = st.get("mhz")
        out["is_stock"] = st.get("is_stock")
        out["persists"] = st.get("persists")
        out.setdefault("ok", True)
    return out


def tune(freq_mhz: int, mv: int, persist: bool = False,
         cap_points: int = 25, dry_run: bool = False) -> dict[str, Any]:
    """应用「电压上限 + 该电压下的频率」，把 V/F 曲线拉平。

    freq_mhz 为目标频率；mv 为电压上限（mV）。
    persist=True 时写入登录任务，开机自动重应用。
    """
    args = ["--mv", str(int(mv)), "--mhz", str(int(freq_mhz)),
            "--cap-points", str(int(cap_points))]
    if dry_run:
        args.append("--dry-run")
    if not persist:
        args.append("--no-persist")
    r = _run(args, timeout=240)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or r.get("out", "")[:300],
                "raw": r.get("out", "")}
    out = r["out"]
    m = _OP_POINT.search(out)
    applied = {"ok": True, "raw": out}
    if m:
        applied["mv"] = int(m.group(1))
        applied["mhz"] = int(m.group(2))
    if "mv" not in applied:
        # 有些运行路径不回显工作点，直接回读状态确认（更可靠）
        st = status()
        if st.get("ok") and not st.get("is_stock"):
            applied["mv"] = st.get("mv")
            applied["mhz"] = st.get("mhz")
        elif st.get("ok"):
            applied["ok"] = False
            applied["error"] = "写入后状态仍为原厂曲线"
    core.log(f"NVAPI 调参：{freq_mhz}MHz @ {mv}mV "
             f"（{'已持久化' if persist else '临时'}）", source="nvbackend")
    return applied


def clear() -> dict[str, Any]:
    """恢复原厂：清空曲线偏移并移除登录任务。"""
    r = _run(["clear"], timeout=180)
    if r.get("ok"):
        core.log("NVAPI 调参已恢复原厂", source="nvbackend")
    return {"ok": r.get("ok", False),
            "error": r.get("error") or r.get("out", "")[:300],
            "raw": r.get("out", "")}
