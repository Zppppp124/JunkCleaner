"""基于 NVAPI 的降压搜索（不依赖 MSI Afterburner）。

与原 AdaptiveUndervolt（操作 Afterburner Profile 文件）的区别：
  * 通过 nvbackend 直接调用 NVAPI，无需 Afterburner 运行
  * 可以读到**真实核心电压**，不再靠曲线推算
  * 搜索逻辑按用户要求：从当前稳定电压起，每档 -25mV 下探，
    一旦某一档失败就回退到上一档稳定值并停止（阶梯法）

每档的判定标准（三重，缺一不可）：
  1. 频率达标：满载平均频率不低于目标的 97%
  2. 无掉频：满载期间没有明显掉频采样
  3. 数值正确：负载输出没有 NaN/Inf/异常峰值（花屏类静默损坏）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from . import core, gpu, gpu_load, nvbackend


@dataclass
class NvUndervoltResult:
    target_freq: int = 0
    start_mv: float = 0.0
    lowest_stable_mv: float = 0.0
    suggested_mv: float = 0.0
    margin_mv: float = 0.0
    attempts: list[dict[str, Any]] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    applied: bool = False
    persisted: bool = False
    backend: str = "nvapi"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NvAdaptiveUndervolt:
    """阶梯式降压搜索（NVAPI 后端）。"""

    def __init__(self, freq: int, test_seconds: int = 60,
                 step_mv: float = 25.0, start_mv: float = 0.0,
                 floor_mv: float = 850.0, max_steps: int = 0,
                 margin_mv: float = 0.0, transient: bool = True,
                 progress: Callable[[str], None] | None = None) -> None:
        self.freq = int(freq)
        self.test_seconds = int(test_seconds)
        self.step = float(step_mv)
        self.start_mv = float(start_mv or 0)
        self.floor = float(floor_mv)
        self.max_steps = int(max_steps)
        self.margin = max(0.0, float(margin_mv))
        self.transient = bool(transient)
        self.progress = progress or (lambda _m: None)
        self._stop = False

    # ---------------- 工具 ----------------
    def _log(self, msg: str) -> None:
        core.log(msg, source="nvundervolt")
        try:
            self.progress(msg)
        except Exception:  # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._stop = True

    def _apply(self, mv: float) -> dict[str, Any]:
        """按「目标频率 @ 电压上限」应用，返回工具的结果。"""
        return nvbackend.tune(self.freq, int(round(mv)), persist=False)

    def _verify(self, mv: float) -> dict[str, Any]:
        """跑一段带数值校验的瞬态负载，判定该档是否稳定。"""
        loader = gpu_load.GpuStress(transient=self.transient)
        loader.start()
        time.sleep(2.0)
        if not loader.running:
            note = loader.startup_error or (loader.errors or
                                            ["GPU 负载未能启动"])[0]
            loader.stop()
            # 关键区分：负载没跑起来属于「环境/后端问题」，
            # 不能当成「该电压不稳定」，否则会得到完全错误的结论。
            return {"ok": False, "load_error": True,
                    "reason": f"压测负载无法启动：{note}",
                    "attempt": mv}

        clocks: list[int] = []
        utils: list[int] = []
        powers: list[float] = []
        temps: list[int] = []
        end = time.time() + max(5, self.test_seconds)
        try:
            while time.time() < end and not self._stop:
                time.sleep(1.0)
                st = gpu.read_state()
                clocks.append(st.clock_graphics)
                utils.append(st.utilization)
                powers.append(st.power_draw)
                temps.append(st.temperature)
                # 数值损坏（花屏类）会立刻记录
                ext = getattr(loader, "_external", None)
                if ext is not None and ext.corruption():
                    break
                # 负载进程异常退出（驱动重置）
                if ext is not None and not ext.alive and \
                        ext.returncode not in (None, 0):
                    break
        finally:
            loader.stop()

        corrupt = ""
        ext = getattr(loader, "_external", None)
        if ext is not None:
            corrupt = ext.corruption()
        # 只看真正满载的样本：瞬态模式会在轻载与满载间跳变，
        # 低载样本的时钟天然偏低，算进去会误判为「掉频」。
        busy = [c for c, u in zip(clocks, utils) if u >= 90]
        avg = int(sum(busy) / len(busy)) if busy else 0
        dropped = sum(1 for c in busy if c < self.freq * 0.95)
        reasons = []
        if corrupt:
            reasons.append(f"检出数值损坏（{corrupt}）")
        if not busy:
            reasons.append("未采集到满载样本")
        elif avg < self.freq * 0.97:
            reasons.append(f"满载频率仅 {avg}MHz，低于目标 {self.freq}MHz")
        if dropped:
            reasons.append(f"掉频 {dropped} 次")
        return {
            "ok": not reasons,
            "reason": "；".join(reasons),
            "attempt": mv,
            "samples": len(clocks),
            "busy": len(busy),
            "clock_avg": avg,
            "clock_min": min(busy) if busy else 0,
            "power_max": int(max(powers)) if powers else 0,
            "temp_max": max(temps) if temps else 0,
            "dropped": dropped,
            "corruption": corrupt,
        }

    # ---------------- 主流程 ----------------
    def run(self) -> NvUndervoltResult:
        res = NvUndervoltResult(target_freq=self.freq)
        if not core.is_admin():
            res.error = "需要管理员权限"
            return res
        if not nvbackend.available():
            res.error = "未找到 NVAPI 调参工具（simple-nvidia-undervolt）"
            return res

        # 预检：压测后端不可用时提前失败，避免动过一次电压之后才发现
        # 「负载起不来」，那样既浪费时间又容易让人误以为是电压问题。
        backend = gpu_load.stress_backend()
        if not backend.get("ok"):
            res.error = (f"{backend.get('error')}。\n\n"
                         "提示：本版本把 OpenCL 压测器内嵌在程序中，"
                         "只要 NVIDIA 驱动正常即可使用；"
                         "若文件被杀软删除，请恢复后重试。")
            return res
        self._log(f"压测后端：{backend.get('mode')}")

        st = nvbackend.status()
        if not st.get("ok"):
            res.error = f"无法读取显卡状态：{st.get('error')}"
            return res

        # 起点电压：优先用当前已应用的值，否则用用户指定／曲线推算
        start = float(self.start_mv or st.get("mv") or 0)
        if start <= 0:
            curve = nvbackend.read_curve()
            if curve.get("ok"):
                near = min(curve["points"],
                           key=lambda p: abs(p[1] - self.freq),
                           default=None)
                if near:
                    start = float(near[0])
        if start <= 0:
            res.error = "无法确定起始电压，请手动指定"
            return res
        res.start_mv = start

        self._log(f"目标 {self.freq}MHz，起始电压 {start:.0f}mV，"
                  f"每档 -{self.step:.0f}mV，下限 {self.floor:.0f}mV，"
                  f"单档 {self.test_seconds}s"
                  f"（{'瞬态' if self.transient else '恒定'}负载）")

        # 先确认起点本身稳定，且记住它的实际落到电压
        applied = self._apply(start)
        if not applied.get("ok"):
            res.error = (f"起始电压 {start:.0f}mV 应用失败："
                         f"{applied.get('error')}")
            return res
        landed = float(applied.get("mv") or start)
        self._log(f"起始档 {landed:.0f}mV 验证中…")
        r = self._verify(landed)
        res.attempts.append(r)
        if not r.get("ok"):
            if r.get("load_error"):
                # 不能把「压测没跑起来」说成「电压不稳」，否则会误导排查。
                res.error = (f"{r.get('reason')}。\n\n"
                             "这是压测环境问题，不是起始电压的问题；"
                             "请确认已安装 NVIDIA 驱动后重试。"
                             "如仍失败，请在「运行日志」页查看详情。")
            else:
                res.error = (f"起始电压 {landed:.0f}mV 就不稳定"
                             f"（{r.get('reason')}），请从更高电压开始")
            return res
        stable_mv = landed
        best_backup = landed
        self._log(f"  ✓ {landed:.0f}mV 稳定")

        mv = landed - self.step
        steps = 0
        while mv >= self.floor:
            if self._stop:
                res.error = "已取消"
                break
            if self.max_steps and steps >= self.max_steps:
                self._log(f"已达最大步数 {self.max_steps}，停止")
                break
            self._log(f"尝试 {mv:.0f}mV …")
            applied = self._apply(mv)
            if not applied.get("ok"):
                # 应用失败本身也是「电压不足」的强信号
                self._log(f"  ✗ {mv:.0f}mV 应用失败："
                          f"{applied.get('error')}")
                res.attempts.append({"attempt": mv, "ok": False,
                                     "reason": "应用失败（疑似电压不足）"})
                self._apply(best_backup)
                break
            actual = float(applied.get("mv") or mv)
            r = self._verify(actual)
            r["attempt"] = mv
            res.attempts.append(r)
            steps += 1
            if r.get("ok"):
                stable_mv = actual
                best_backup = actual
                self._log(f"  ✓ {actual:.0f}mV 稳定")
                mv = actual - self.step
            else:
                if r.get("load_error"):
                    res.error = (f"{r.get('reason')}。\n\n"
                                 "这是压测环境问题，不是电压结论；已回退到"
                                 f"上一稳定档 {best_backup:.0f}mV。")
                    self._apply(best_backup)
                    break
                self._log(f"  ✗ {mv:.0f}mV 不稳定（{r.get('reason')}），回退")
                self._apply(best_backup)
                break

        res.lowest_stable_mv = stable_mv
        # 建议值默认等于「最低稳定电压」：搜索本身就是每档 25mV 的阶梯，
        # 最后停在的稳定档已经天然带了一档余量（下一档已验证失败）。
        # 若用户显式要求额外余量（margin_mv>0），才再加。
        suggested = stable_mv
        if self.margin > 0:
            suggested = min(stable_mv + self.margin, start)
        res.suggested_mv = suggested
        res.margin_mv = round(suggested - stable_mv, 1)
        res.ok = True
        self._log(f"最低稳定 {stable_mv:.0f}mV；建议使用 {suggested:.0f}mV"
                  f"（+{res.margin_mv:.0f}mV 余量）")
        return res

    def apply_final(self, mv: float, persist: bool = True
                    ) -> dict[str, Any]:
        """把最终选择应用（可选择持久化到开机自动重应用）。"""
        r = nvbackend.tune(self.freq, int(round(mv)), persist=persist)
        if r.get("ok"):
            r["persisted"] = bool(persist)
        return r
