"""GPU 调优（NVIDIA，通过 nvidia-smi）。

能力边界（实测本机 nvidia-smi 支持情况）
---------------------------------------
支持：
  * --lock-gpu-clocks / --lock-memory-clocks  锁定频率
  * --power-limit / --power-limit=  --set      功耗墙
  * --reset-gpu-clocks                         恢复默认
  * 查询 clocks / power / temperature / fan / utilization / throttle

不支持（重要）：
  * --voltage   ！nvidia-smi 没有任何电压设置接口
  * --fan       ！nvidia-smi 无法设置风扇转速

真正的 GPU 降压/风扇控制走 NVIDIA 私有 NVAPI（MSI Afterburner 用的就是它），
且新版驱动对消费卡的电压写入做了一致性限制。本模块不伪造这些能力，
只把「能稳的东西」做扎实：锁频 + 功耗墙 + 稳定性验证 + 开机固化。

频率/功耗设置在重启后会丢失，因此提供「固化」：注册计划任务在开机时重新应用。
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable

from . import core

TASK_NAME = "JunkCleaner GPU Tune"


def smi_path() -> str:
    p = shutil.which("nvidia-smi")
    if p:
        return p
    for c in (r"C:\Windows\System32\nvidia-smi.exe",
              r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        if Path(c).exists():
            return c
    return ""


def available() -> bool:
    return bool(smi_path())


def _run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    exe = smi_path()
    if not exe:
        return -1, "未找到 nvidia-smi"
    proc = core.run([exe, *args], timeout=timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    return proc.returncode, out


# --------------------------------------------------------------------------
# 读取状态
# --------------------------------------------------------------------------
@dataclass
class GpuState:
    name: str = ""
    driver: str = ""
    clock_graphics: int = 0
    clock_memory: int = 0
    clock_max: int = 0
    power_draw: float = 0.0
    power_limit: float = 0.0
    power_max: float = 0.0
    temperature: int = 0
    fan: int = 0
    utilization: int = 0
    throttle: str = ""
    locked_graphics: int = 0
    locked_memory: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(text: str) -> float:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group(0)) if m else 0.0


def read_state() -> GpuState:
    """读取 GPU 当前状态。"""
    st = GpuState()
    fields = ("name,driver_version,clocks.gr,clocks.mem,clocks.max.gr,"
              "power.draw,power.limit,power.max_limit,temperature.gpu,"
              "fan.speed,utilization.gpu,clocks_throttle_reasons.active")
    rc, out = _run([f"--query-gpu={fields}", "--format=csv,noheader"])
    if rc != 0 or not out:
        return st
    parts = [p.strip() for p in out.splitlines()[0].split(",")]
    if len(parts) < 11:
        return st
    st.name = parts[0]
    st.driver = parts[1]
    st.clock_graphics = int(_num(parts[2]))
    st.clock_memory = int(_num(parts[3]))
    st.clock_max = int(_num(parts[4]))
    st.power_draw = _num(parts[5])
    st.power_limit = _num(parts[6])
    st.power_max = _num(parts[7])
    st.temperature = int(_num(parts[8]))
    st.fan = int(_num(parts[9]))
    st.utilization = int(_num(parts[10]))
    st.throttle = parts[11] if len(parts) > 11 else ""
    # 读取当前锁定值（若已锁）
    rc2, out2 = _run(["-q", "-d", "CLOCK"])
    if rc2 == 0 and out2:
        for key, attr in (("Graphics", "locked_graphics"),
                          ("Memory", "locked_memory")):
            block = re.search(rf"{key}\s+:\s+(\d+) MHz", out2)
            if block:
                setattr(st, attr, int(block.group(1)))
    return st


def capabilities() -> dict[str, Any]:
    """探测 nvidia-smi 支持哪些操作（用于界面显示真实能力）。"""
    rc, help_text = _run(["--help"])
    caps = {
        "lock_clocks": "--lock-gpu-clocks" in help_text,
        "lock_memory": "--lock-memory-clocks" in help_text,
        "power_limit": "--power-limit" in help_text,
        "reset_clocks": "--reset-gpu-clocks" in help_text,
        "voltage": "--voltage" in help_text,   # 实测为 False
        "fan": "--fan" in help_text,           # 实测为 False
    }
    return caps


# --------------------------------------------------------------------------
# 应用设置
# --------------------------------------------------------------------------
def lock_clocks(graphics: int, memory: int = 0) -> dict[str, Any]:
    """锁定 GPU 频率。memory=0 表示只锁核心。"""
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    args = [f"--lock-gpu-clocks={graphics}"]
    if memory:
        args.append(f"--lock-memory-clocks={memory}")
    rc, out = _run(args)
    ok = rc == 0
    core.log(f"锁频 {graphics}MHz: {'成功' if ok else out[:120]}", source="gpu")
    return {"ok": ok, "graphics": graphics, "memory": memory, "detail": out}


def set_power_limit(watts: int) -> dict[str, Any]:
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    rc, out = _run(["--power-limit", str(int(watts))])
    ok = rc == 0
    core.log(f"设置功耗墙 {watts}W: {'成功' if ok else out[:120]}", source="gpu")
    return {"ok": ok, "watts": int(watts), "detail": out}


def reset_clocks() -> dict[str, Any]:
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    rc, out = _run(["--reset-gpu-clocks"])
    return {"ok": rc == 0, "detail": out}


# --------------------------------------------------------------------------
# 稳定性验证（不测电压，只验证目标频率能否稳定运行）
# --------------------------------------------------------------------------
def stability_test(target_clock: int, seconds: int = 60,
                   progress: Callable[[str], None] | None = None,
                   stress: bool = False,
                   lock_clock: bool = True) -> dict[str, Any]:
    """把时钟锁到目标频率并观察一段时间：温度、降频原因、是否掉频。

    注意：这不是「找最低电压」——电压不可控。它验证的是
    「该频率在当前供电/散热下能否长时间稳定」。

    stress=True 时会用 PyTorch 让 GPU 真正满载，
    这样降压不稳导致的掉频/驱动重置才能暴露出来。
    """
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    if lock_clock:
        r = lock_clocks(target_clock)
        if not r.get("ok"):
            return {"ok": False, "error": f"锁频失败：{r.get('detail')}"}

    loader = None
    stress_summary: dict[str, Any] = {}
    if stress:
        try:
            from . import gpu_load
            backend = gpu_load.stress_backend()
            if backend.get("ok"):
                loader = gpu_load.GpuStress()
                loader.start()
                if not loader.running:
                    stress_summary["note"] = (
                        (loader.errors or ["CUDA 负载未能启动"])[0])
                    loader = None
                else:
                    time.sleep(3.0)      # 等负载起来
            else:
                stress_summary["note"] = backend.get("error") or "CUDA 不可用"
        except Exception as exc:  # noqa: BLE001
            stress_summary["note"] = f"负载启动失败：{exc}"

    samples: list[dict[str, Any]] = []
    start = time.time()
    try:
        while time.time() - start < seconds:
            st = read_state()
            samples.append({"t": round(time.time() - start, 1),
                            "clock": st.clock_graphics,
                            "temp": st.temperature,
                            "power": st.power_draw,
                            "throttle": st.throttle,
                            "util": st.utilization})
            if progress:
                try:
                    extra = ("  满载" if loader else "")
                    progress(f"{st.clock_graphics}MHz / {st.temperature}°C / "
                             f"{st.power_draw:.0f}W / {st.utilization}%{extra}")
                except Exception:  # noqa: BLE001
                    pass
            if loader and loader.errors:
                break
            # 打包版使用外部 CUDA 进程做负载；若它异常退出（驱动重置），
            # 这里必须判为不稳定，否则会误报稳定。
            ext = getattr(loader, "_external", None) if loader else None
            if ext is not None and not ext.alive and ext.returncode not in (None, 0):
                loader.errors.append(
                    f"CUDA 负载进程异常退出（rc={ext.returncode}），"
                    "通常代表电压不足导致驱动重置")
                break
            time.sleep(2.0)
    finally:
        if loader:
            loader.stop()
            stress_summary = loader.summary()

    clocks = [s["clock"] for s in samples] or [0]
    temps = [s["temp"] for s in samples] or [0]
    powers = [s["power"] for s in samples] or [0]
    dropped = sum(1 for c in clocks if c < target_clock * 0.95)
    stress_errors = list((stress_summary or {}).get("errors") or [])
    if loader is not None and loader.errors:
        stress_errors.extend(loader.errors)
    stress_errors = list(dict.fromkeys(str(e) for e in stress_errors if e))
    # 只统计「真正的」降频原因；bit0 是 GpuIdle（空闲自动降频），不算问题
    real_throttle = 0
    throttle_names: set[str] = set()
    for s in samples:
        raw = s.get("throttle", "") or ""
        m = re.search(r"0x([0-9a-fA-F]+)", raw)
        if not m:
            continue
        bits = int(m.group(1), 16)
        active = bits & ~0x1          # 去掉 GpuIdle
        if active:
            real_throttle += 1
            throttle_names.add(raw)
    return {
        "ok": dropped == 0 and not stress_errors,
        "stressed": bool(loader is not None),
        "stress": stress_summary,
        "stress_errors": stress_errors,
        "reason": ("；".join(stress_errors[:2]) if stress_errors else
                   ("负载下掉频" if dropped else "")),
        "target": target_clock,
        "samples": len(samples),
        "clock_min": min(clocks), "clock_avg": int(sum(clocks) / len(clocks)),
        "clock_max": max(clocks),
        "temp_max": max(temps), "temp_avg": int(sum(temps) / len(temps)),
        "power_max": max(powers),
        "dropped": dropped, "throttled": real_throttle,
        "throttle_reasons": sorted(throttle_names),
        "detail": samples[-1] if samples else {},
    }


# --------------------------------------------------------------------------
# 开机固化（重启后 nvidia-smi 设置会丢失）
# --------------------------------------------------------------------------
def save_profile(clock: int, memory: int = 0, watts: int = 0) -> Path:
    path = core.data_dir() / "gpu_profile.json"
    path.write_text(json.dumps({
        "clock": int(clock), "memory": int(memory or 0),
        "watts": int(watts or 0),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_profile() -> dict[str, Any]:
    try:
        return json.loads((core.data_dir() / "gpu_profile.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_saved_profile() -> dict[str, Any]:
    prof = load_profile()
    if not prof:
        return {"ok": False, "error": "没有已保存的 GPU 配置"}
    results: list[str] = []
    if prof.get("watts"):
        r = set_power_limit(int(prof["watts"]))
        results.append(f"功耗墙 {prof['watts']}W={r.get('ok')}")
    if prof.get("clock"):
        r = lock_clocks(int(prof["clock"]), int(prof.get("memory") or 0))
        results.append(f"锁频 {prof['clock']}MHz={r.get('ok')}")
    return {"ok": True, "results": results}


def _entry_args() -> tuple[str, str]:
    """返回（可执行文件, 参数），用于计划任务。"""
    import sys
    if getattr(sys, "frozen", False):
        return sys.executable, "--gpu-apply"
    entry = Path(__file__).resolve().parents[1] / "junkcleaner_entry.py"
    return core.python_exe_windowless(), f'"{entry}" --gpu-apply'


def _ps_literal(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def install_autostart() -> dict[str, Any]:
    """注册开机任务，登录后重新应用 GPU 配置。"""
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    exe, args = _entry_args()
    ps = (
        f"$a=New-ScheduledTaskAction -Execute {_ps_literal(exe)} "
        f"-Argument {_ps_literal(args)};"
        "$t=New-ScheduledTaskTrigger -AtLogOn;"
        "$p=New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest;"
        "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
        "-DontStopIfGoingOnBatteries -StartWhenAvailable "
        "-ExecutionTimeLimit (New-TimeSpan -Seconds 0);"
        f"Register-ScheduledTask -TaskName {_ps_literal(TASK_NAME)} "
        "-Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null; 'OK'")
    proc = core.run_powershell(ps, timeout=60)
    ok = b"OK" in (proc.stdout or b"")
    core.log(f"GPU 固化任务: {'成功' if ok else '失败'}", source="gpu")
    return {"ok": ok, "detail": (proc.stdout or b"").decode("utf-8", "replace")}


def remove_autostart() -> dict[str, Any]:
    proc = core.run_powershell(
        f"Unregister-ScheduledTask -TaskName {_ps_literal(TASK_NAME)} "
        f"-Confirm:$false -ErrorAction SilentlyContinue; 'OK'", timeout=60)
    return {"ok": b"OK" in (proc.stdout or b"")}


def autostart_installed() -> bool:
    proc = core.run_powershell(
        f"if(Get-ScheduledTask -TaskName {_ps_literal(TASK_NAME)} "
        f"-ErrorAction SilentlyContinue){{'YES'}}else{{'NO'}}", timeout=30)
    return b"YES" in (proc.stdout or b"")


# --------------------------------------------------------------------------
# CPU 调压能力检测（如实告知，不提供自动搜索）
# --------------------------------------------------------------------------
def cpu_undervolt_support() -> dict[str, Any]:
    """检测 CPU 调压是否可行，并说明原因。"""
    info: dict[str, Any] = {"cpu": "", "msr_driver": False,
                            "undervolt_likely_blocked": False,
                            "reasons": [], "suggestions": []}
    script = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "(Get-CimInstance Win32_Processor).Name")
    info["cpu"] = (core.run_powershell(script, timeout=40).stdout or b"") \
        .decode("utf-8", "replace").strip()

    # 常见 MSR 驱动/服务
    drivers = []
    for root in (r"C:\Windows\System32\drivers",):
        p = Path(root)
        if p.exists():
            for pat in ("WinRing0*", "inpout*", "iocbios*", "RTCore*",
                        "NTIOLib*", "ThrottleStop*"):
                drivers.extend(p.glob(pat))
    info["msr_driver"] = bool(drivers)
    if not drivers:
        info["reasons"].append("没有找到 MSR 访问驱动（WinRing0/inpoutx64 等）")
    if "13th Gen" in info["cpu"] or "12th Gen" in info["cpu"]:
        info["undervolt_likely_blocked"] = True
        info["reasons"].append(
            "Intel 12/13 代在 2023 年后的微码中启用了 Undervolt Protection，"
            "MSR 0x150 写入会被固件拒绝")
    info["suggestions"] = [
        "在 BIOS 中用 Offset 模式降压（最稳妥，直接生效且开机持久）",
        "或使用 Intel XTU / ThrottleStop 手动逐步测试（它们自带所需驱动）",
        "本工具不自动遍历电压——每次失败都是强制重启，有损坏文件系统风险",
    ]
    return info
