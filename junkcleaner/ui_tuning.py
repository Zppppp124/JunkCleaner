"""电源 / GPU 调优页面。

CPU 调压部分只做「能力检测 + 说明」，不提供自动搜索电压：
13 代 Intel 微码已启用 Undervolt Protection，且自动遍历电压需要
反复让系统崩溃，有损坏文件系统风险。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import core, gpu, gpu_live, power, undervolt, vfcurve

GOOD = "#2ec4a5"
WARN = "#ff9f43"
DANGER = "#f4577c"
MUTED = "#8d86a8"
TEXT = "#3a3352"
ACCENT = "#8b6cf6"
SOFT = "#efe9ff"


class Worker(QThread):
    done = Signal(str, dict)

    def __init__(self, kind: str, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.kind = kind
        self.fn = fn

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)}
        self.done.emit(self.kind, result if isinstance(result, dict)
                       else {"ok": True, "value": result})


class StressWorker(QThread):
    progress = Signal(str)
    done = Signal(dict)

    def __init__(self, clock: int, seconds: int) -> None:
        super().__init__()
        self.clock = clock
        self.seconds = seconds

    def run(self) -> None:
        r = gpu.stability_test(self.clock, seconds=self.seconds,
                               progress=lambda m: self.progress.emit(m))
        self.done.emit(r)


class UndervoltWorker(QThread):
    """后台跑降压搜索（支持取消）。"""

    progress = Signal(str)
    done = Signal(dict)

    def __init__(self, freq: int, seconds: int, step: float, floor: float,
                 max_steps: int = 0, section: str = "Profile1",
                 margin: float = 25.0, transient: bool = True) -> None:
        super().__init__()
        self.freq = freq
        self.seconds = seconds
        self.step = step
        self.floor = floor
        self.max_steps = max_steps
        self.section = section
        self.margin = margin
        self.transient = transient
        self.engine: undervolt.AdaptiveUndervolt | None = None

    def run(self) -> None:
        self.engine = undervolt.AdaptiveUndervolt(
            freq=self.freq, test_seconds=self.seconds, step_mv=self.step,
            floor_mv=self.floor, max_steps=self.max_steps,
            section=self.section,
            margin_mv=self.margin,
            transient=self.transient,
            progress=lambda m: self.progress.emit(m))
        self.done.emit(self.engine.run().to_dict())

    def cancel(self) -> None:
        if self.engine:
            self.engine.cancel()


class TuningPage(QWidget):
    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.notify = notify
        self.set_status = status or (lambda _m: None)
        self._worker: QThread | None = None
        self._stress: QThread | None = None
        self._uv: QThread | None = None
        self._last_uv: dict[str, Any] = {}
        self._clock_initialized = False
        self._live_state: dict[str, Any] = {}
        # 页面内容较高，放进滚动区，避免窗口偏小时控件被压扁、
        # 文字互相重叠。右下角的实时数据区本身有固定高度。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self._scroll.setWidget(inner)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)
        self._content = inner
        self._build()
        self.refresh()
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(1000)
        self._live_timer.timeout.connect(self._refresh_live)
        self._live_timer.start()

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self._content)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(11)

        self.sys_label = QLabel("")
        self.sys_label.setObjectName("Muted")
        self.sys_label.setWordWrap(True)
        lay.addWidget(self.sys_label)

        # 电源方案与 GPU 面板改为上下排列：并排时两块的
        # 最小宽度相加会超过窗口，导致右侧内容被裁掉。
        top = QVBoxLayout()
        top.setSpacing(11)

        # ---- 电源方案 ----
        pw = QGroupBox("电源方案")
        pg = QGridLayout(pw)
        self.lbl_power = QLabel("—")
        self.lbl_power.setWordWrap(True)
        self.cmb_plan = QComboBox()
        self.btn_power = QPushButton("启用卓越性能")
        self.btn_power.setObjectName("Primary")
        self.btn_power.clicked.connect(self.enable_ultimate)
        self.btn_tune = QPushButton("性能项调优")
        self.btn_tune.setObjectName("Ghost")
        self.btn_tune.clicked.connect(self.tune_processor)
        self.btn_plan_apply = QPushButton("切换到所选方案")
        self.btn_plan_apply.setObjectName("Ghost")
        self.btn_plan_apply.clicked.connect(self.apply_plan)
        pg.addWidget(self.lbl_power, 0, 0, 1, 3)
        pg.addWidget(self.cmb_plan, 1, 0, 1, 2)
        pg.addWidget(self.btn_plan_apply, 1, 2)
        pg.addWidget(self.btn_power, 2, 0)
        pg.addWidget(self.btn_tune, 2, 1, 1, 2)
        top.addWidget(pw)

        # ---- GPU ----
        gw = QGroupBox("GPU（NVIDIA）")
        gg = QGridLayout(gw)
        self.lbl_gpu = QLabel("读取中…")
        self.lbl_gpu.setWordWrap(True)
        self.lbl_gpu.setTextFormat(Qt.RichText)
        self.lbl_live = QLabel("实时：等待 Afterburner 监控…")
        self.lbl_live.setWordWrap(True)
        self.lbl_live.setTextFormat(Qt.RichText)
        self.lbl_live.setStyleSheet(
            f"color:{TEXT};font-weight:600;font-size:13px;")
        self.spin_clock = QSpinBox()
        self.spin_clock.setRange(500, 4000)
        self.spin_clock.setSingleStep(15)
        self.spin_clock.setSuffix(" MHz")
        self.spin_clock.valueChanged.connect(
            lambda _v: self._refresh_curve())
        self.spin_watts = QSpinBox()
        self.spin_watts.setRange(50, 600)
        self.spin_watts.setSuffix(" W")
        self.spin_stress = QSpinBox()
        self.spin_stress.setRange(10, 600)
        # 默认 300 秒：稳态满载要跑得足够久，才能暴露供电瞬态不足。
        # 单档太短（如 60 秒）会把临界不稳定的电压误判为「稳定」。
        self.spin_stress.setValue(300)
        self.spin_stress.setSuffix(" 秒")
        self.spin_stress.setToolTip(
            "单档满载验证时长。建议 ≥300 秒；时间越短越容易把临界电压误判为稳定。")
        # 瞬态负载：在满载与轻载间反复跳变，制造电流突变，更接近游戏工况。
        self.check_transient = QCheckBox("瞬态负载模式")
        self.check_transient.setChecked(True)
        self.check_transient.setToolTip(
            "在满载与轻载间反复跳变，制造电流突变（dv/dt）。\n"
            "游戏花屏多由这种瞬态压降引起，恒定满载测不出来。")
        self.btn_lock = QPushButton("锁定频率")
        self.btn_lock.setObjectName("Primary")
        self.btn_lock.clicked.connect(self.lock_gpu)
        self.btn_power_limit = QPushButton("设置功耗墙")
        self.btn_power_limit.setObjectName("Ghost")
        self.btn_power_limit.clicked.connect(self.set_gpu_power)
        self.btn_stress = QPushButton("稳定性验证")
        self.btn_stress.setObjectName("Ghost")
        self.btn_stress.clicked.connect(self.run_stress)
        self.btn_reset_gpu = QPushButton("恢复默认")
        self.btn_reset_gpu.setObjectName("Ghost")
        self.btn_reset_gpu.clicked.connect(self.reset_gpu)
        self.btn_gpu_persist = QPushButton("固化（开机自动应用）")
        self.btn_gpu_persist.setObjectName("Ghost")
        self.btn_gpu_persist.clicked.connect(self.persist_gpu)
        head = QWidget()
        head_lay = QVBoxLayout(head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(4)
        head_lay.addWidget(self.lbl_live)
        head_lay.addWidget(self.lbl_gpu)
        gg.addWidget(head, 0, 0, 1, 4)
        # 让信息区至少留出两行文字的高度，避免被其它行挤到重叠
        head.setMinimumHeight(52)
        gg.addWidget(QLabel("目标频率"), 1, 0)
        gg.addWidget(self.spin_clock, 1, 1)
        gg.addWidget(QLabel("功耗墙"), 1, 2)
        gg.addWidget(self.spin_watts, 1, 3)
        gg.addWidget(QLabel("验证时长"), 2, 0)
        gg.addWidget(self.spin_stress, 2, 1)
        gg.addWidget(self.check_transient, 2, 2, 1, 2)
        gg.addWidget(self.btn_lock, 3, 0, 1, 4)
        gg.addWidget(self.btn_power_limit, 4, 0, 1, 2)
        gg.addWidget(self.btn_stress, 4, 2, 1, 2)
        gg.addWidget(self.btn_reset_gpu, 5, 0, 1, 2)
        gg.addWidget(self.btn_gpu_persist, 5, 2, 1, 2)

        # ---- 降压调优（走 Afterburner V/F 曲线）----
        ab = vfcurve.afterburner_dir()
        self.lbl_ab = QLabel(
            f"Afterburner：{ab}" if ab else
            "未检测到 MSI Afterburner（降压功能需要它）")
        self.lbl_ab.setWordWrap(True)
        self.lbl_ab.setStyleSheet(
            f"color:{GOOD if ab else WARN};font-weight:600;")
        gg.addWidget(self.lbl_ab, 6, 0, 1, 4)

        self.lbl_curve = QLabel("—")
        self.lbl_curve.setWordWrap(True)
        self.lbl_curve.setTextFormat(Qt.RichText)
        gg.addWidget(self.lbl_curve, 7, 0, 1, 4)

        self.spin_step = QSpinBox()
        self.spin_step.setRange(5, 100)
        self.spin_step.setSingleStep(5)
        self.spin_step.setValue(25)
        self.spin_step.setSuffix(" mV")
        self.spin_floor = QSpinBox()
        self.spin_floor.setRange(600, 1100)
        self.spin_floor.setSingleStep(25)
        self.spin_floor.setValue(800)
        self.spin_floor.setSuffix(" mV")
        gg.addWidget(QLabel("每档降压"), 8, 0)
        gg.addWidget(self.spin_step, 8, 1)
        gg.addWidget(QLabel("电压下限"), 8, 2)
        gg.addWidget(self.spin_floor, 8, 3)

        self.cmb_slot = QComboBox()
        self.cmb_slot.setToolTip("搜索完成后把锁定曲线写入这个 Afterburner 预设槽位")
        gg.addWidget(QLabel("保存到预设"), 9, 0)
        gg.addWidget(self.cmb_slot, 9, 1, 1, 3)

        self.btn_uv_search = QPushButton("自动搜索最低稳定电压")
        self.btn_uv_search.setObjectName("Primary")
        self.btn_uv_search.clicked.connect(self.start_undervolt)
        self.btn_uv_cancel = QPushButton("停止搜索")
        self.btn_uv_cancel.setObjectName("Danger")
        self.btn_uv_cancel.setEnabled(False)
        self.btn_uv_cancel.clicked.connect(self.cancel_undervolt)
        self.btn_uv_restore = QPushButton("还原曲线备份")
        self.btn_uv_restore.setObjectName("Ghost")
        self.btn_uv_restore.clicked.connect(self.restore_curve)
        self.btn_uv_apply = QPushButton("一键应用并固化")
        self.btn_uv_apply.setObjectName("Primary")
        self.btn_uv_apply.setToolTip(
            "把最近一次搜索的稳定结果写入所选预设，并设为 Afterburner 启动预设")
        self.btn_uv_apply.setEnabled(False)
        self.btn_uv_apply.clicked.connect(self.apply_undervolt_preset)
        gg.addWidget(self.btn_uv_search, 10, 0, 1, 2)
        gg.addWidget(self.btn_uv_cancel, 10, 2)
        gg.addWidget(self.btn_uv_restore, 10, 3)
        gg.addWidget(self.btn_uv_apply, 11, 0, 1, 4)
        top.addWidget(gw)
        lay.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        lay.addWidget(self.progress)

        # ---- 结果 ----
        res = QGroupBox("验证结果 / 能力说明")
        rv = QVBoxLayout(res)
        self.result = QTableWidget(0, 2)
        self.result.setHorizontalHeaderLabels(["项目", "结果"])
        self.result.verticalHeader().setVisible(False)
        self.result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        head = self.result.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.result.setColumnWidth(0, 200)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        rv.addWidget(self.result)
        lay.addWidget(res, 1)

        # ---- CPU 调压说明 ----
        cpu_box = QGroupBox("CPU 调压能力检测（只读，不自动尝试）")
        cv = QVBoxLayout(cpu_box)
        self.cpu_label = QLabel("检测中…")
        self.cpu_label.setWordWrap(True)
        self.cpu_label.setTextFormat(Qt.RichText)
        cv.addWidget(self.cpu_label)
        lay.addWidget(cpu_box)

    # ---------------- 数据 ----------------
    def refresh(self) -> None:
        info = power.windows_info()
        fam = info.get("family", "未知")
        self.sys_label.setText(
            f"系统：{info.get('Caption','')}　Build {info.get('Build','')}"
            f"（识别为 {fam}）　架构 {info.get('Arch','')}")

        cur = power.current_plan()
        ult = power.find_ultimate()
        self.lbl_power.setText(
            f"当前：<b>{cur.name if cur else '未知'}</b><br>"
            f"卓越性能：{'已创建 ' + ult.guid if ult else '未创建（点击左侧按钮创建并启用）'}")
        self.cmb_plan.blockSignals(True)
        self.cmb_plan.clear()
        for p in power.list_plans():
            label = f"{p.name}{'（当前）' if p.active else ''}"
            self.cmb_plan.addItem(label, p.guid)
        self.cmb_plan.blockSignals(False)
        reasons = power.plan_forbidden_reasons()
        if reasons and self.notify:
            self.set_status("；".join(reasons))

        self._refresh_gpu()
        self._refresh_curve()
        self._render_cpu()

    def _refresh_gpu(self) -> None:
        if not gpu.available():
            self.lbl_gpu.setText("未检测到 nvidia-smi（可能是非 NVIDIA 显卡）")
            self.spin_clock.setEnabled(False)
            self.spin_watts.setEnabled(False)
            return
        caps = gpu.capabilities()
        st = gpu.read_state()
        # 只在首次进入页面时给一个初始值；之后绝不再覆盖用户输入，
        # 否则每次刷新/搜索完都会跳回 3150，无法固定目标频率。
        if not self._clock_initialized:
            self.spin_clock.setValue(max(500, st.clock_max or st.clock_graphics))
            self._clock_initialized = True
        self.spin_watts.setRange(int(st.power_max * 0.5) or 50,
                                 int(st.power_max) or 600)
        if not getattr(self, "_watts_initialized", False):
            self.spin_watts.setValue(int(st.power_limit) or 200)
            self._watts_initialized = True
        # 这里只显示一段简短的卡信息；实时数据在 lbl_live，
        # 曲线详情在下方的 lbl_curve，避免文字过多互相挤压。
        self.lbl_gpu.setText(
            f"<b>{st.name}</b>　驱动 {st.driver}　"
            f"上限 {st.clock_max} MHz　功耗墙上限 {st.power_max:.0f} W　"
            f"<span style='color:{MUTED}'>"
            f"nvidia-smi 锁频 {'✓' if caps['lock_clocks'] else '✗'}　"
            f"功耗墙 {'✓' if caps['power_limit'] else '✗'}</span>")

    def _refresh_live(self) -> None:
        """每秒刷新一次：直接用 Afterburner 监控共享内存的真实数据。"""
        live = gpu_live.read_state()
        self._live_state = live
        if not live.get("ok"):
            # 回退到 nvidia-smi（拿不到电压，但频率/功耗/温度仍可显示）
            st = gpu.read_state()
            if not st.name:
                self.lbl_live.setText(
                    f"<span style='color:{MUTED}'>实时：未检测到 GPU / "
                    "Afterburner 监控未运行</span>")
                return
            self.lbl_live.setText(
                f"<span style='color:{MUTED}'>实时（nvidia-smi）：</span>"
                f"<b>{st.clock_graphics} MHz</b>　"
                f"{st.power_draw:.0f} W　{st.temperature}°C　"
                f"{st.utilization}%　"
                f"<span style='color:{WARN}'>电压：Afterburner 未发布</span>")
            self._refresh_curve()
            return

        clock = int(live.get("clock_mhz") or 0)
        mv = float(live.get("voltage_mv") or 0)
        if mv > 0:
            volt_txt = f"电压 <b style='color:{GOOD}'>{mv:.0f} mV</b>　"
        else:
            # 该卡/驱动下 Afterburner 不发布核心电压数据源，
            # 用当前生效曲线按实时频率推算，并如实标注来源。
            volt_txt = ""
        self.lbl_live.setText(
            f"<span style='color:{ACCENT}'>● 实时</span>　"
            f"频率 <b>{clock} MHz</b>　{volt_txt}"
            f"功耗 <b>{live.get('power_w', 0):.0f} W</b>　"
            f"{live.get('temperature_c', 0)}°C　"
            f"占用 {live.get('usage_pct', 0)}%　"
            f"风扇 {live.get('fan_pct', 0)}%")
        self._refresh_curve()

    def _render_cpu(self) -> None:
        s = gpu.cpu_undervolt_support()
        color = DANGER if s.get("undervolt_likely_blocked") else WARN
        parts = [f"<b>CPU：</b>{s.get('cpu','')}<br>"]
        if s.get("reasons"):
            parts.append(f"<span style='color:{color}'>检测到的限制：</span>")
            parts.append("<ul style='margin:2px 0 2px 16px'>"
                         + "".join(f"<li>{r}</li>" for r in s["reasons"])
                         + "</ul>")
        parts.append(f"<span style='color:{MUTED}'>建议：</span>")
        parts.append("<ul style='margin:2px 0 0 16px'>"
                     + "".join(f"<li>{x}</li>" for x in s.get("suggestions", []))
                     + "</ul>")
        self.cpu_label.setText("".join(parts))

    def _refresh_curve(self) -> None:
        """显示当前**实际生效**的 V/F 曲线，以及目标频率对应的电压。

        之前读的是 Defaults（出厂基准），所以永远显示 1240mV/3150MHz，
        和你当前实际运行的 815mV/2835MHz 对不上。现在读当前生效段，
        并用 Afterburner 实时电压优先显示。
        """
        prof = vfcurve.find_gpu_profile()
        if prof is None:
            self.lbl_curve.setText("未找到 GPU Profile，降压功能不可用")
            self.btn_uv_search.setEnabled(False)
            if hasattr(self, "btn_uv_apply"):
                self.btn_uv_apply.setEnabled(False)
            return
        self.btn_uv_search.setEnabled(True)
        # 槽位下拉只在内容变化时重建，避免每秒刷新打断用户选择
        if hasattr(self, "cmb_slot"):
            slots = vfcurve.profile_slots(prof) or ["Profile1"]
            existing = [self.cmb_slot.itemText(i)
                        for i in range(self.cmb_slot.count())]
            if existing != slots:
                current = self.cmb_slot.currentText()
                self.cmb_slot.blockSignals(True)
                self.cmb_slot.clear()
                for s in slots:
                    self.cmb_slot.addItem(s)
                if current in slots:
                    self.cmb_slot.setCurrentText(current)
                self.cmb_slot.blockSignals(False)
            startup = vfcurve.get_startup_profile()
            if startup > 0:
                self.cmb_slot.setToolTip(
                    f"当前 Afterburner 启动预设：Profile{startup}")

        # 优先显示当前生效段（Startup），拿不到再看 Profile1 / Defaults
        sec = ""
        c = None
        for name in ("Startup", "Profile1"):
            c = vfcurve.read_curve(prof, name)
            if c and c.points:
                sec = name
                break
        if c is None or not c.points:
            c, sec = vfcurve.read_base_curve(prof)
        if not c:
            self.lbl_curve.setText("无法解析 V/F 曲线")
            return

        # 先显示实时频率对应的曲线电压（最贴近你现在跑的状态），
        # 没有实时数据时退回用户输入的目标频率。
        live_clock = int((self._live_state or {}).get("clock_mhz") or 0)
        target = live_clock or self.spin_clock.value()
        v = c.voltage_for_freq(float(target))
        vt = "—" if v is None else f"{v:.0f} mV"
        boost = vfcurve.read_core_boost(prof, sec)
        boost_txt = ""
        if boost is not None and boost != 0:
            boost_txt = (f"　<span style='color:{WARN}'>"
                         f"核心偏移 {boost}（会压低实际频率）</span>")
        # 实时电压优先（Afterburner 未发布电压时回退到曲线值）
        live_mv = float((self._live_state or {}).get("voltage_mv") or 0)
        which = "实时" if live_clock else "目标"
        if live_mv > 0:
            live_txt = f"　|　实时电压 <b>{live_mv:.0f} mV</b>"
        else:
            live_txt = (f"　|　{which}电压 <b>{vt}</b>"
                        f"<span style='color:{MUTED}'>（按生效曲线推算）</span>")
        self.lbl_curve.setText(
            f"当前生效 [{sec}] {len(c.points)} 点，最高 "
            f"{c.max_freq:.0f}MHz @ {c.max_voltage:.0f}mV{boost_txt}　|　"
            f"{which} {target}MHz{live_txt}")

    # ---------------- 操作 ----------------
    def _run(self, kind: str, fn: Callable[[], Any]) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.progress.setFormat(f"{kind}…")
        self._worker = Worker(kind, fn)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, kind: str, result: dict[str, Any]) -> None:
        self.progress.setFormat(f"{kind} 完成")
        ok = result.get("ok")
        msg = result.get("error") or result.get("detail") or ""
        self.set_status(f"{kind}：{'成功' if ok else '失败'} {msg}".strip())
        if not ok and msg:
            QMessageBox.warning(self, kind, str(msg))
        self.refresh()
        # refresh 会按“没有搜索结果”把按钮禁用；如果刚完成的是
        # 一键应用，就把状态恢复成可用，且保留最近搜索结果。
        if kind == "应用并固化 GPU 预设" and ok and self._last_uv:
            self.btn_uv_apply.setEnabled(True)
        elif self._last_uv.get("lowest_stable_mv"):
            self.btn_uv_apply.setEnabled(True)

    def enable_ultimate(self) -> None:
        if QMessageBox.question(
                self, "启用卓越性能",
                "创建并切换到「卓越性能」电源方案？\n\n"
                "该方案会更激进地保持高频率（关闭核心停歇延迟），"
                "适合台式机；笔记本会明显更耗电。选择本身会持久保存。"
        ) != QMessageBox.Yes:
            return
        self._run("启用卓越性能", power.enable_ultimate)

    def tune_processor(self) -> None:
        self._run("处理器性能项调优", power.tune_processor)

    def apply_plan(self) -> None:
        guid = self.cmb_plan.currentData()
        if not guid:
            return
        self._run("切换电源方案", lambda: power.set_active(guid))

    def lock_gpu(self) -> None:
        c = self.spin_clock.value()
        self._run(f"锁定 {c}MHz", lambda: gpu.lock_clocks(c))

    def set_gpu_power(self) -> None:
        w = self.spin_watts.value()
        self._run(f"功耗墙 {w}W", lambda: gpu.set_power_limit(w))

    def reset_gpu(self) -> None:
        self._run("恢复 GPU 默认", gpu.reset_clocks)

    def persist_gpu(self) -> None:
        c = self.spin_clock.value()
        w = self.spin_watts.value()
        if QMessageBox.question(
                self, "固化 GPU 配置",
                f"保存并在每次开机时自动应用：\n频率 {c} MHz，功耗墙 {w} W？\n\n"
                "会注册一个开机计划任务（需管理员权限）。"
        ) != QMessageBox.Yes:
            return

        def work() -> dict[str, Any]:
            gpu.save_profile(c, 0, w)
            r = gpu.install_autostart()
            r["profile"] = gpu.load_profile()
            return r

        self._run("固化 GPU 配置", work)

    def run_stress(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        c = self.spin_clock.value()
        secs = self.spin_stress.value()
        if QMessageBox.question(
                self, "稳定性验证",
                f"把频率锁定到 {c} MHz 并观察 {secs} 秒？\n\n"
                "期间会记录实际频率 / 温度 / 功耗 / 降频原因。\n"
                "注意：这不测电压（nvidia-smi 不支持设置电压），"
                "只验证该频率在当前供电散热下是否稳定。"
        ) != QMessageBox.Yes:
            return
        self.btn_stress.setEnabled(False)
        self.progress.setValue(0)
        self._stress = StressWorker(c, secs)
        self._stress.progress.connect(
            lambda m: self.progress.setFormat(f"验证中 {m}"))
        self._stress.done.connect(self._on_stress)
        self._stress.start()

    # ---------------- 降压调优 ----------------
    def start_undervolt(self) -> None:
        if self._uv and self._uv.isRunning():
            return
        freq = self.spin_clock.value()
        secs = self.spin_stress.value()
        step = float(self.spin_step.value())
        floor = float(self.spin_floor.value())
        section = self.cmb_slot.currentText() or "Profile1"
        prof = vfcurve.find_gpu_profile()
        c, base_sec = vfcurve.read_base_curve(prof) if prof else (None, "")
        orig = c.voltage_for_freq(freq) if c else None
        if orig is None:
            QMessageBox.warning(self, "无法开始",
                                "无法读取该频率的当前电压，请确认 Afterburner "
                                "已配置并且是 NVIDIA 显卡。")
            return
        if c is not None and freq > c.max_freq:
            QMessageBox.warning(
                self, "频率超出曲线范围",
                f"目标 {freq} MHz 超过当前 V/F 曲线的最高 "
                f"{c.max_freq:.0f} MHz。\n\n"
                "请把目标频率调到曲线范围内（例如 2760 MHz），"
                "或先在 Afterburner 里刷新一次曲线。")
            return
        est = max(1, int((orig - floor) / step))
        margin = max(0.0, float(self.spin_step.value()))
        transient = bool(self.check_transient.isChecked())
        msg = (
            f"目标频率：{freq} MHz\n"
            f"当前电压：{orig:.0f} mV\n"
            f"基准曲线：[{base_sec}]\n"
            f"计划保存到：{section}（搜索完成后可一键应用并固化）\n"
            f"每档降压：-{step:.0f} mV，下限 {floor:.0f} mV\n"
            f"单档满载验证：{secs} 秒\n"
            f"负载模式：{'瞬态（满载↔轻载跳变）' if transient else '恒定满载'}\n"
            f"稳定后余量：+{margin:.0f} mV（建议电压会自动加这一档）\n"
            f"预计最多 {est} 档（约 {est * (secs + 8) // 60} 分钟）\n\n"
            "流程：每档会短暂关闭 Afterburner（避免它用内存里的旧预设\n"
            "覆盖我们写入的曲线）→ 写入曲线并归零核心频率偏移 → 重启\n"
            "Afterburner 加载 → PyTorch 满载压测 + 数值校验 → 稳定就继续降。\n"
            "注意：压测是稳态负载，游戏是瞬态负载，所以搜索出的最低稳定\n"
            "电压会再留一档余量作为建议值，避免游戏里花屏。\n"
            "搜索期间屏幕可能闪一下、Afterburner 托盘图标短暂消失，属正常。\n"
            "全程会先备份曲线；若中途出问题会自动还原，不会留下不稳定配置。\n\n"
            "开始后请勿运行其他大型 3D 程序。是否继续？")
        if QMessageBox.question(self, "自动搜索最低稳定电压", msg) != QMessageBox.Yes:
            return
        self.btn_uv_search.setEnabled(False)
        self.btn_uv_cancel.setEnabled(True)
        self.btn_uv_apply.setEnabled(False)
        self.progress.setValue(0)
        self._uv = UndervoltWorker(freq, secs, step, floor, section=section,
                                   margin=margin, transient=transient)
        self._uv.progress.connect(
            lambda m: self.progress.setFormat(m[:110]))
        self._uv.done.connect(self._on_undervolt)
        self._uv.start()

    def cancel_undervolt(self) -> None:
        if self._uv and self._uv.isRunning():
            self._uv.cancel()
            self.progress.setFormat("正在停止（会固定在最后一档稳定值）…")

    def _on_undervolt(self, r: dict[str, Any]) -> None:
        self.btn_uv_search.setEnabled(True)
        self.btn_uv_cancel.setEnabled(False)
        self.progress.setFormat("降压搜索结束")
        self._last_uv = dict(r)

        rows = [("目标频率", f"{r.get('target_freq')} MHz"),
                ("原始电压", f"{r.get('original_mv'):.0f} mV"),
                ("最低稳定电压", f"{r.get('lowest_stable_mv'):.0f} mV"),
                ("建议电压（含余量）",
                 f"{r.get('suggested_mv', 0):.0f} mV"
                 f"（+{r.get('margin_mv', 0):.0f} mV）"),
                ("降压幅度", f"{r.get('original_mv', 0) - r.get('best_mv', 0):.0f} mV"),
                ("保存预设", str(r.get("section") or "—")),
                ("启动预设", f"Profile{r.get('startup_profile')}"
                 if r.get("startup_profile", -1) > 0 else "—")]
        for a in r.get("attempts") or []:
            rows.append((f"  {a['mv']:.0f} mV",
                         ("稳定" if a.get("ok") else "不稳定")
                         + (f"　频率{a['clock_avg']}MHz"
                            if a.get("clock_avg") else "")
                         + (f"　温度{a['temp_max']}°C"
                            if a.get("temp_max") else "")
                         + (f"　掉频{a['dropped']}次"
                            if a.get("dropped") else "")))
        self.result.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.result.setItem(i, 0, QTableWidgetItem(str(k)))
            item = QTableWidgetItem(str(v))
            if "不稳定" in str(v):
                item.setForeground(Qt.red)
            elif "稳定" in str(v):
                item.setForeground(Qt.darkGreen)
            self.result.setItem(i, 1, item)

        if r.get("error"):
            QMessageBox.warning(self, "降压搜索", str(r["error"]))
        if r.get("ok") and r.get("attempts"):
            QMessageBox.information(
                self, "降压完成",
                f"最低稳定电压（压测结果）：{r.get('lowest_stable_mv'):.0f} mV\n"
                f"建议使用电压：{r.get('suggested_mv', 0):.0f} mV"
                f"（已加 {r.get('margin_mv', 0):.0f} mV 安全余量）\n"
                f"（原始 {r.get('original_mv'):.0f} mV，"
                f"降低 {r.get('original_mv', 0) - r.get('best_mv', 0):.0f} mV）\n\n"
                "说明：压测是稳态满载，游戏是瞬态负载，同电压下游戏可能\n"
                "更容易花屏。所以默认加一档余量，一键应用时会使用「建议\n"
                "使用电压」。写完预设后请用真实游戏再验证一段时间。")
            self.btn_uv_apply.setEnabled(True)
        if self.notify:
            self.notify("GPU 降压完成",
                        f"{r.get('target_freq')}MHz @ "
                        f"{r.get('suggested_mv', r.get('lowest_stable_mv', 0)):.0f}mV")
        self.refresh()

    def apply_undervolt_preset(self) -> None:
        """把最近一次搜索结果重新写入所选槽位并设为启动预设。"""
        r = dict(self._last_uv or {})
        if not r or not r.get("lowest_stable_mv"):
            QMessageBox.information(
                self, "还没有结果",
                "请先运行一次「自动搜索最低稳定电压」。")
            return
        prof = vfcurve.find_gpu_profile()
        if prof is None:
            QMessageBox.warning(self, "无法应用", "未找到 GPU Profile。")
            return
        section = self.cmb_slot.currentText() or "Profile1"
        freq = int(r.get("target_freq") or self.spin_clock.value())
        # 默认应用「建议电压」（最低稳定值 + 安全余量），而不是临界值。
        # 稳态压测通过不等于游戏瞬态负载也稳。
        low = float(r.get("lowest_stable_mv") or 0)
        mv = float(r.get("suggested_mv") or 0) or low
        if mv <= 0:
            return
        margin_note = (f"（最低稳定 {low:.0f} mV，"
                       f"加 {mv - low:.0f} mV 余量）"
                       if mv > low else "")
        if QMessageBox.question(
                self, "一键应用并固化",
                f"把 {freq} MHz @ {mv:.0f} mV 写入 [{section}]，\n"
                f"{margin_note}\n"
                "并设为 Afterburner 启动预设（开机自动应用）？\n\n"
                "会先备份当前 Profile。") != QMessageBox.Yes:
            return

        def work() -> dict[str, Any]:
            vfcurve.backup_profile(prof)
            curve, _sec = vfcurve.read_base_curve(prof)
            if curve is None:
                return {"ok": False, "error": "无法读取基准曲线"}
            curve.lock_frequency(freq, mv)
            r2 = vfcurve.write_locked_profile(
                prof, curve, section=section, make_startup=True)
            r2["section"] = section
            r2["startup_profile"] = vfcurve.get_startup_profile()
            r2["target_freq"] = freq
            r2["lowest_stable_mv"] = mv
            # 回读曲线，确认写入真的落在目标段
            check = vfcurve.read_curve(prof, section)
            got = check.voltage_for_freq(freq) if check else None
            r2["verify_mv"] = got
            r2["verify_ok"] = got is not None and abs(got - mv) < 1.0
            if r2.get("ok") and not r2["verify_ok"]:
                r2["ok"] = False
                r2["error"] = ("预设写入后回读电压不一致"
                               f"（期望 {mv:.0f}mV，读到 {got}）")
            if r2.get("ok"):
                vfcurve.reload_profile(int(r2.get("startup_profile") or 1))
            return r2

        self.btn_uv_apply.setEnabled(False)
        self._run("应用并固化 GPU 预设", work)

    def restore_curve(self) -> None:
        backs = vfcurve.list_backups()
        if not backs:
            QMessageBox.information(self, "无备份", "还没有曲线备份。")
            return
        prof = vfcurve.find_gpu_profile()
        if not prof:
            return
        from pathlib import Path as _P
        latest = backs[0]
        if QMessageBox.question(
                self, "还原曲线",
                f"用备份 {latest['time']} 覆盖当前 V/F 曲线？\n"
                "（会立即应用到 Afterburner）") != QMessageBox.Yes:
            return
        r = vfcurve.restore_profile(_P(latest["_file"]), prof)
        if r.get("ok"):
            vfcurve.reload_profile(1)
            QMessageBox.information(self, "已还原", "V/F 曲线已还原并应用。")
        else:
            QMessageBox.warning(self, "失败", str(r.get("error")))
        self.refresh()

    def _on_stress(self, r: dict[str, Any]) -> None:
        self.btn_stress.setEnabled(True)
        self.progress.setFormat("验证完成")
        rows = [
            ("目标频率", f"{r.get('target')} MHz"),
            ("实际频率", f"最低 {r.get('clock_min')} / 平均 "
                        f"{r.get('clock_avg')} / 最高 {r.get('clock_max')} MHz"),
            ("掉频次数", f"{r.get('dropped')} 次"),
            ("温度", f"最高 {r.get('temp_max')}°C / 平均 {r.get('temp_avg')}°C"),
            ("峰值功耗", f"{r.get('power_max')} W"),
            ("真实降频原因", "、".join(r.get("throttle_reasons") or []) or "无"),
            ("结论", "稳定" if r.get("ok") else "存在掉频，建议降低频率"),
        ]
        self.result.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.result.setItem(i, 0, QTableWidgetItem(k))
            item = QTableWidgetItem(str(v))
            if k == "结论":
                item.setForeground(Qt.darkGreen if r.get("ok") else Qt.red)
            self.result.setItem(i, 1, item)
        if self.notify:
            self.notify("GPU 稳定性验证完成",
                        f"{r.get('target')}MHz："
                        f"{'稳定' if r.get('ok') else '有掉频'}")
        self.refresh()
