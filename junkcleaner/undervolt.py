"""GPU 降压调优：指定频率，自动搜索最低稳定电压。

为什么这个可以做，而 CPU 的不行
-------------------------------
GPU 走 Afterburner 的 Profile（V/F 曲线）+ RTCore 驱动，写入是驱动级、
**不会让系统崩溃**：电压不够时 NVIDIA 驱动会直接**重置显卡驱动**
（画面黑一下、事件日志出现 Display 41），系统本身不受影响。
CPU 降压失败则是整个系统硬重启，风险完全不同。

搜索策略（二分 + 稳定性验证）
-----------------------------
1. 先确保目标频率在当前曲线里可达（否则提示超出范围）
2. 电压上界 = 原始曲线该频率对应的电压（安全起点）
3. 下界 = 用户设定的最低电压（默认 800mV，低于此不管）
4. 逐档下降（默认 25mV 一步），每档应用后跑稳定性验证
5. 失败立即回退到上一个已知稳定档，并**自动还原到稳定配置**
6. 全程有超时保护，异常时恢复备份

每次失败都会：先把 Profile 还原成上一个稳定版本 → 重新应用 →
等驱动恢复 → 再继续下一轮。这样即使中途中断，显卡也不会停在
一个不稳定的电压上。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

from . import core, gpu, vfcurve


@dataclass
class UndervoltResult:
    target_freq: int = 0
    original_mv: float = 0.0
    best_mv: float = 0.0
    lowest_stable_mv: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    profile: str = ""
    backup: str = ""
    section: str = ""
    startup_profile: int = -1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AdaptiveUndervolt:
    """自适应降压搜索。"""

    def __init__(self, freq: int, test_seconds: int = 300,
                 step_mv: float = 25.0, floor_mv: float = 800.0,
                 window_mhz: float = 200.0,
                 max_steps: int = 0,
                 section: str = "Profile1",
                 progress: Callable[[str], None] | None = None) -> None:
        self.freq = int(freq)
        self.test_seconds = int(test_seconds)
        self.step = float(step_mv)
        self.floor = float(floor_mv)
        self.window = float(window_mhz)
        self.max_steps = int(max_steps)   # 0 = 不限
        self.section = section or "Profile1"
        self.progress = progress or (lambda _m: None)
        self.profile: Path | None = None
        self.backup: Path | None = None
        self._stop = False

    # ---------------- 内部工具 ----------------
    def _log(self, msg: str) -> None:
        core.log(msg, source="undervolt")
        try:
            self.progress(msg)
        except Exception:  # noqa: BLE001
            pass

    def _apply_voltage(self, mv: float) -> bool:
        """把曲线锁成「目标频率 @ mv」，并让 Afterburner 真正加载它。

        关键流程：Afterburner 运行时不会重读外部修改的 Profile，
        因此必须「先退出 -> 写文件 -> 再启动」。否则曲线写对了，
        实际时钟仍停在旧预设上，就会一直误判为频率不达标。
        """
        assert self.profile
        # 1) 退出 Afterburner（保留 RTSS）
        stop = vfcurve.stop_afterburner()
        if not stop.get("ok"):
            self._log(f"关闭 Afterburner 失败：{stop.get('error')}")
            return False
        # 2) 从干净基准重建曲线并写入
        curve, _base_section = vfcurve.read_base_curve(self.profile)
        if curve is None:
            return False
        lock = curve.lock_frequency(self.freq, mv)
        if not lock.get("ok"):
            return False
        r = vfcurve.write_curve(self.profile, curve,
                                sections=["Startup", "Profile1"])
        if not r.get("ok"):
            return False
        # 同步解除历史遗留的核心频率偏移，否则曲线写对了频率也上不去。
        vfcurve.clear_core_boost(self.profile)
        # 3) 重新启动 Afterburner，让它从磁盘加载这份曲线
        vfcurve.reload_profile(1)
        time.sleep(2.0)
        return True

    def _restore_stable(self, backup: Path) -> None:
        """把 Profile 还原到已知稳定状态并应用。"""
        if self.profile:
            vfcurve.restore_profile(backup, self.profile)
            vfcurve.reload_profile(1)
            time.sleep(3.0)

    def _wait_driver(self, timeout: int = 30) -> bool:
        """降压失败后等驱动恢复（出现驱动重置时 nvidia-smi 会短暂失败）。"""
        end = time.time() + timeout
        while time.time() < end:
            st = gpu.read_state()
            if st.name:
                return True
            time.sleep(2)
        return False

    def _test(self, mv: float) -> dict[str, Any]:
        """应用 mv 并验证稳定性。"""
        if not self._apply_voltage(mv):
            return {"mv": mv, "ok": False, "reason": "写入/应用失败"}
        st = gpu.read_state()
        if not st.name:
            self._wait_driver()
            return {"mv": mv, "ok": False, "reason": "驱动无响应（可能已重置）"}
        # 关键：搜索期间不要再用 nvidia-smi 锁频，否则它会和 Afterburner
        # 的 V/F 曲线互相覆盖，导致「设了 2760 却实际停在别处」。
        # 这里只跑负载，频率由曲线平台决定。
        r = gpu.stability_test(self.freq, seconds=self.test_seconds,
                               progress=self._log, stress=True,
                               lock_clock=False)
        r["mv"] = mv
        if not r.get("stressed"):
            note = (r.get("stress") or {}).get("note") or "未启动满载负载"
            r["ok"] = False
            r["reason"] = (f"无法进行满载验证（{note}）。"
                           "最低稳定电压必须在真实满载下测出，已中止。")
            return r
        # 曲线锁频是否真的达到了目标频率
        ok_clock = (r.get("clock_avg") or 0) >= self.freq * 0.97
        r["clock_ok"] = ok_clock
        if not ok_clock:
            r["ok"] = False
            r["reason"] = (
                f"满载频率只到 {r.get('clock_avg')}MHz，"
                f"低于目标 {self.freq}MHz")
        return r

    # ---------------- 主流程 ----------------
    def run(self) -> UndervoltResult:
        res = UndervoltResult(target_freq=self.freq)
        if not core.is_admin():
            res.error = "需要管理员权限"
            return res
        if not vfcurve.afterburner_dir():
            res.error = "未找到 MSI Afterburner"
            return res

        self.profile = vfcurve.find_gpu_profile()
        if self.profile is None:
            res.error = "未找到 GPU Profile"
            return res
        res.profile = str(self.profile)
        res.section = self.section

        curve, base_section = vfcurve.read_base_curve(self.profile)
        if curve is None or not curve.points:
            res.error = "无法解析 V/F 曲线"
            return res

        peak = curve.max_freq
        if self.freq > peak:
            res.error = f"目标 {self.freq}MHz 超出曲线最高 {peak:.0f}MHz"
            return res

        orig = curve.voltage_for_freq(self.freq)
        if orig is None:
            res.error = "无法确定该频率的原始电压"
            return res
        res.original_mv = float(orig)
        res.best_mv = float(orig)

        self.backup = vfcurve.backup_profile(self.profile)
        res.backup = str(self.backup)
        stable_backup = self.backup
        stable_mv = float(orig)

        self._log(f"目标 {self.freq}MHz，基准曲线 [{base_section}]，"
                  f"原始电压 {orig:.0f}mV，"
                  f"每档 -{self.step:.0f}mV，单档测试 {self.test_seconds}s")

        mv = float(orig) - self.step
        steps_done = 0
        try:
            while mv >= self.floor:
                if self.max_steps and steps_done >= self.max_steps:
                    self._log(f"已达最大步数 {self.max_steps}，停止搜索")
                    break
                if self._stop:
                    res.error = "已取消"
                    break
                self._log(f"尝试 {mv:.0f}mV …")
                r = self._test(mv)
                steps_done += 1
                res.attempts.append({
                    "mv": mv, "ok": bool(r.get("ok")),
                    "clock_avg": r.get("clock_avg"), "clock_min": r.get("clock_min"),
                    "temp_max": r.get("temp_max"), "power_max": r.get("power_max"),
                    "dropped": r.get("dropped"),
                    "reasons": r.get("throttle_reasons") or [],
                    "note": r.get("reason", ""),
                })
                if r.get("ok"):
                    stable_mv = mv
                    res.best_mv = mv
                    # 这一档稳定，把它保存为新的回退点
                    stable_backup = vfcurve.backup_profile(self.profile)
                    self._log(f"  ✓ {mv:.0f}mV 稳定")
                else:
                    self._log(f"  ✗ {mv:.0f}mV 不稳定"
                              f"（{r.get('reason') or '掉频' }），回退")
                    self._restore_stable(stable_backup)
                    self._wait_driver()
                    break
                mv -= self.step

            res.lowest_stable_mv = stable_mv
            res.ok = stable_mv < float(orig)
            if not res.ok and not res.error:
                res.error = "未找到比原始更低的稳定电压"
        finally:
            # 无论成功失败，最终都停在「已知稳定」的配置上
            if stable_backup and self.profile:
                self._restore_stable(stable_backup)
                self._log(f"已固定在 {stable_mv:.0f}mV")
                # 搜索阶段只保留“已知稳定”的临时状态；真正生成预设、
                # 设置开机启动由界面上的「一键应用并固化」显式确认后执行。
                # 这样用户仍有“只测不稳定值、不改预设”的自由。
        return res

    def cancel(self) -> None:
        self._stop = True
