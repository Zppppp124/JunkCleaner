"""电源 / GPU 调优页面。

CPU 调压部分只做「能力检测 + 说明」，不提供自动搜索电压：
13 代 Intel 微码已启用 Undervolt Protection，且自动遍历电压需要
反复让系统崩溃，有损坏文件系统风险。
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import (core, gpu, gpu_live, nvbackend, nvundervolt, power, undervolt,
               vfcurve)

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


class LiveFetchWorker(QThread):
    """后台读取实时状态。

    为什么需要：读取走的是外部进程（每次约 40ms），如果直接在 UI 线程里
    每秒同步调用，主线程会被反复阻塞，界面表现为卡顿。
    放到子线程后主线程只负责渲染，不再等待进程往返。
    """

    done = Signal(dict)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            data = nvbackend.read_live()
        except Exception as exc:  # noqa: BLE001
            data = {"ok": False, "error": str(exc)}
        self.done.emit(data)


class PowerFetchWorker(QObject):
    """后台查询电源方案。

    注意：这里用 Python 原生线程 + 信号，而不是 QThread。
    原因：这些查询内部是阻塞的 subprocess 调用；如果做成 QThread，
    退出时若线程仍在等待子进程，Qt 析构会直接让进程以
    0xc0000409 崩溃（即使调用了 wait/terminate）。
    用守护线程则进程退出时由解释器直接回收，不会触发该问题。
    """

    done = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._alive = False

    @property
    def is_running(self) -> bool:
        return self._alive

    def start(self) -> None:
        import threading
        if self._alive:
            return
        self._alive = True
        threading.Thread(target=self._run, name="JC-PowerFetch",
                         daemon=True).start()

    def _run(self) -> None:
        data: dict[str, Any] = {}
        try:
            data["sys"] = power.windows_info()
        except Exception:  # noqa: BLE001
            data["sys"] = {}
        try:
            cur = power.current_plan()
            data["current"] = ({"name": cur.name, "guid": cur.guid}
                               if cur else None)
        except Exception:  # noqa: BLE001
            data["current"] = None
        try:
            ult = power.find_ultimate()
            data["ultimate"] = ({"name": ult.name, "guid": ult.guid}
                                if ult else None)
        except Exception:  # noqa: BLE001
            data["ultimate"] = None
        try:
            data["plans"] = [{"name": p.name, "guid": p.guid,
                              "active": p.active}
                             for p in power.list_plans()]
        except Exception:  # noqa: BLE001
            data["plans"] = []
        try:
            data["reasons"] = power.plan_forbidden_reasons()
        except Exception:  # noqa: BLE001
            data["reasons"] = []
        try:
            data["cpu_uv"] = gpu.cpu_undervolt_support()
        except Exception:  # noqa: BLE001
            data["cpu_uv"] = {}
        self._alive = False
        self.done.emit(data)


class GpuFetchWorker(QThread):
    """后台查询 GPU 状态（nvidia-smi 子进程，约 110ms）。"""

    done = Signal(dict)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        data: dict[str, Any] = {"available": gpu.available()}
        if data["available"]:
            try:
                data["state"] = gpu.read_state().to_dict()
            except Exception:  # noqa: BLE001
                data["state"] = {}
            try:
                data["caps"] = gpu.capabilities()
            except Exception:  # noqa: BLE001
                data["caps"] = {}
        self.done.emit(data)


class UndervoltWorker(QThread):
    """后台跑降压搜索（NVAPI 后端，支持取消）。"""

    progress = Signal(str)
    done = Signal(dict)

    def __init__(self, freq: int, seconds: int, step: float, floor: float,
                 start_mv: float = 0.0, max_steps: int = 0,
                 transient: bool = True) -> None:
        super().__init__()
        self.freq = freq
        self.seconds = seconds
        self.step = step
        self.floor = floor
        self.start_mv = start_mv
        self.max_steps = max_steps
        self.transient = transient
        self.engine: nvundervolt.NvAdaptiveUndervolt | None = None

    def run(self) -> None:
        self.engine = nvundervolt.NvAdaptiveUndervolt(
            freq=self.freq, test_seconds=self.seconds, step_mv=self.step,
            start_mv=self.start_mv, floor_mv=self.floor,
            max_steps=self.max_steps,
            transient=self.transient,
            progress=lambda m: self.progress.emit(m))
        self.done.emit(self.engine.run().to_dict())

    def cancel(self) -> None:
        if self.engine:
            self.engine.cancel()


class NvUndervoltWorker(UndervoltWorker):
    """兼容旧名字（界面里按这个类名构造）。"""

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
        # 后台刷新用的线程句柄（必须在 refresh() 之前初始化，
        # 否则 refresh 里判断 isRunning() 会 AttributeError）
        self._live_worker: LiveFetchWorker | None = None
        self._power_worker: PowerFetchWorker | None = None
        self._gpu_worker: GpuFetchWorker | None = None
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
        # 间隔放宽到 3 秒：读取要走外部进程，1 秒一次没有实际收益，
        # 只会持续占用主线程与 CPU。
        self._live_timer.setInterval(3000)
        self._live_timer.timeout.connect(self._maybe_refresh_live)
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
        self.lbl_live = QLabel("实时：读取中…")
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

        # ---- 降压调优（走 NVAPI，不依赖 Afterburner）----
        # 旧实现依赖 MSI Afterburner 的 Profile 文件；现改为直接调用
        # NVAPI（经 simple-nvidia-undervolt），可读真实电压且无需专有软件。
        nv_ok = nvbackend.available()
        # 显示实际可用的压测后端：内嵌 OpenCL 压测器不依赖 Python/PyTorch，
        # 换电脑时也能跑；这里先展示出来，避免远程排查时靠猜。
        try:
            from . import gpu_load as _gl
            _be = _gl.stress_backend()
        except Exception:  # noqa: BLE001
            _be = {"ok": False}
        if _be.get("ok"):
            stress_txt = (
                f"<span style='color:{GOOD}'>压测后端：内置 OpenCL"
                f"</span>")
        else:
            stress_txt = (
                f"<span style='color:{DANGER}'>压测后端不可用</span>")
        self.lbl_ab = QLabel(
            f"<span style='color:{GOOD}'>NVAPI 直连可用</span>"
            f"　<span style='color:{MUTED}'>无需 MSI Afterburner</span>"
            f"　{stress_txt}"
            if nv_ok else
            f"<span style='color:{WARN}'>未找到 NVAPI 调参组件，"
            "降压功能不可用</span>")
        self.lbl_ab.setWordWrap(True)
        self.lbl_ab.setTextFormat(Qt.RichText)
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

        # NVAPI 直接写显卡，没有 Afterburner 那种「预设槽位」概念，
        # 因此这行改为显示开机固化说明。
        self.lbl_persist = QLabel(
            f"<span style='color:{MUTED}'>"
            "应用后自动注册开机重应用，无需 Afterburner</span>")
        self.lbl_persist.setTextFormat(Qt.RichText)
        gg.addWidget(QLabel("固化方式"), 9, 0)
        gg.addWidget(self.lbl_persist, 9, 1, 1, 3)

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
            "把最近一次搜索的稳定电压写入显卡，并注册开机自动重应用")
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
        """刷新本页。

        注意：电源方案相关的查询全部走 PowerShell，实测一次 refresh 里
        windows_info + current_plan + list_plans + find_ultimate +
        plan_forbidden_reasons 合计约 900ms。如果放在 UI 线程同步执行，
        切到本页时会明显卡住。这里把它们整体挪到后台线程，界面先渲染
        GPU 部分（同样是子进程，也一并异步化）。
        """
        self._start_power_refresh()
        self._start_gpu_refresh()
        self._refresh_curve()

    # ---- 后台刷新：电源方案（PowerShell 重） ----
    def _start_power_refresh(self) -> None:
        if self._power_worker is not None and self._power_worker.is_running:
            return
        self._power_worker = PowerFetchWorker()
        self._power_worker.done.connect(self._apply_power_info)
        self._power_worker.start()

    def _apply_power_info(self, data: dict[str, Any]) -> None:
        sysinfo = data.get("sys") or {}
        fam = sysinfo.get("family", "未知")
        self.sys_label.setText(
            f"系统：{sysinfo.get('Caption','')}　"
            f"Build {sysinfo.get('Build','')}"
            f"（识别为 {fam}）　架构 {sysinfo.get('Arch','')}")
        cur = data.get("current")
        ult = data.get("ultimate")
        cur_name = (cur or {}).get("name") if isinstance(cur, dict) else None
        self.lbl_power.setText(
            f"当前：<b>{cur_name or '未知'}</b><br>"
            f"卓越性能：{'已创建 ' + str(ult['guid']) if ult else '未创建（点击左侧按钮创建并启用）'}")
        plans = data.get("plans") or []
        self.cmb_plan.blockSignals(True)
        self.cmb_plan.clear()
        for p in plans:
            label = f"{p['name']}{'（当前）' if p.get('active') else ''}"
            self.cmb_plan.addItem(label, p.get("guid"))
        self.cmb_plan.blockSignals(False)
        reasons = data.get("reasons") or []
        if reasons and self.notify:
            self.set_status("；".join(reasons))
        self._render_cpu(data.get("cpu_uv") or {})

    # ---- 后台刷新：GPU 状态（nvidia-smi） ----
    def _start_gpu_refresh(self) -> None:
        if self._gpu_worker is not None and self._gpu_worker.isRunning():
            return
        self._gpu_worker = GpuFetchWorker(self)
        self._gpu_worker.done.connect(self._apply_gpu_info)
        self._gpu_worker.start()

    def _apply_gpu_info(self, data: dict[str, Any]) -> None:
        if not data.get("available"):
            self.lbl_gpu.setText("未检测到 nvidia-smi（可能是非 NVIDIA 显卡）")
            self.spin_clock.setEnabled(False)
            self.spin_watts.setEnabled(False)
            return
        st = data.get("state") or {}
        caps = data.get("caps") or {}
        if not self._clock_initialized:
            self.spin_clock.setValue(
                max(500, st.get("clock_max") or st.get("clock_graphics") or 0))
            self._clock_initialized = True
        pmax = st.get("power_max") or 0
        self.spin_watts.setRange(int(pmax * 0.5) or 50, int(pmax) or 600)
        if not getattr(self, "_watts_initialized", False):
            self.spin_watts.setValue(int(st.get("power_limit") or 0) or 200)
            self._watts_initialized = True
        self.lbl_gpu.setText(
            f"<b>{st.get('name','')}</b>　驱动 {st.get('driver','')}　"
            f"上限 {st.get('clock_max', 0)} MHz　"
            f"功耗墙上限 {pmax:.0f} W　"
            f"<span style='color:{MUTED}'>"
            f"nvidia-smi 锁频 {'✓' if caps.get('lock_clocks') else '✗'}　"
            f"功耗墙 {'✓' if caps.get('power_limit') else '✗'}</span>")

    def _maybe_refresh_live(self) -> None:
        """定时器入口：仅在页面可见且无在途请求时刷新。

        页面不可见时完全跳过——否则即使你停在别的页签，这里也会持续
        启动外部进程读显卡，白白占用 CPU 并让整机变钝。
        """
        if not self.isVisible():
            return
        self._refresh_live()

    def _refresh_live(self) -> None:
        """异步刷新：在后台线程读实时数据，主线程只负责渲染。

        读取走外部进程（约 40ms/次），若在 UI 线程同步调用会反复阻塞
        主线程并造成卡顿，因此放到 LiveFetchWorker 里执行。
        """
        if not nvbackend.available():
            # 没有 NVAPI 组件时退回读共享内存（耗时极低，可直接同步）
            self._apply_live(gpu_live.read_state())
            return
        if self._live_worker is not None and self._live_worker.isRunning():
            return      # 上一次还没回来，直接跳过，避免堆积
        self._live_worker = LiveFetchWorker(self)
        self._live_worker.done.connect(self._apply_live)
        self._live_worker.start()

    def _apply_live(self, live: dict[str, Any]) -> None:
        """把后台取回的实时数据渲染到界面（主线程）。"""
        if live.get("source") != "nvapi":
            live = dict(live)
            live.setdefault("source", "afterburner")
        if not live.get("ok"):
            # 回退到 nvidia-smi（拿不到电压，但频率/功耗/温度仍可显示）
            st = gpu.read_state()
            if not st.name:
                self.lbl_live.setText(
                    f"<span style='color:{MUTED}'>实时：未检测到 GPU</span>")
                return
            self.lbl_live.setText(
                f"<span style='color:{MUTED}'>实时（nvidia-smi）：</span>"
                f"<b>{st.clock_graphics} MHz</b>　"
                f"{st.power_draw:.0f} W　{st.temperature}°C　"
                f"{st.utilization}%　"
                f"<span style='color:{WARN}'>电压不可读</span>")
            return

        self._live_state = live
        clock = int(live.get("clock_mhz") or 0)
        mv = float(live.get("voltage_mv") or 0)
        volt_txt = (f"电压 <b style='color:{GOOD}'>{mv:.0f} mV</b>　"
                    if mv > 0 else "")
        # 应用状态（是否已降压、是否开机固化）由同一次后台读取带回
        applied_mv = live.get("applied_mv")
        applied_mhz = live.get("applied_mhz")
        if live.get("is_stock"):
            state_txt = f"　<span style='color:{MUTED}'>原厂曲线</span>"
        elif applied_mv:
            state_txt = (f"　<span style='color:{GOOD}'>已应用 "
                         f"{applied_mv}mV / {applied_mhz or clock}MHz</span>")
        else:
            state_txt = ""
        persist_txt = ("　<span style='color:{0}'>开机固化 ✓</span>".format(GOOD)
                       if live.get("persists") else "")
        self.lbl_live.setText(
            f"<span style='color:{ACCENT}'>● 实时（NVAPI）</span>　"
            f"频率 <b>{clock} MHz</b>　{volt_txt}"
            f"功耗 <b>{live.get('power_w', 0):.0f} W</b>　"
            f"{live.get('temp_c', 0)}°C{state_txt}{persist_txt}")

    def _render_cpu(self, s: dict[str, Any] | None = None) -> None:
        """渲染 CPU 调压能力（数据由后台线程取回，避免阻塞界面）。"""
        if not s:
            s = {"cpu": "", "reasons": [], "suggestions": []}
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
        """刷新曲线/应用状态区域（按需调用，不再每秒执行）。

        这里会读一次显卡状态与曲线（各约 25-45ms）。因为它只在页面
        首次显示、搜索完成、应用完成时调用，对流畅度影响可忽略。
        """
        if not nvbackend.available():
            self.lbl_curve.setText(
                f"<span style='color:{WARN}'>未找到 NVAPI 调参组件，"
                "降压功能不可用</span>")
            self.btn_uv_search.setEnabled(False)
            if hasattr(self, "btn_uv_apply"):
                self.btn_uv_apply.setEnabled(False)
            return
        self.btn_uv_search.setEnabled(True)

        st = nvbackend.status()
        if not st.get("ok"):
            self.lbl_curve.setText(
                f"<span style='color:{WARN}'>无法读取显卡状态："
                f"{st.get('error')}</span>")
            return

        cur_mv = st.get("mv") or 0
        cur_mhz = st.get("mhz") or 0
        if st.get("is_stock"):
            applied_txt = (f"<span style='color:{MUTED}'>当前为原厂曲线"
                           f"（未降压）</span>")
        else:
            applied_txt = f"已应用 <b>{cur_mv} mV / {cur_mhz} MHz</b>"
        if st.get("persists"):
            persist_txt = (f"　<span style='color:{GOOD}'>"
                           "开机自动重应用：已开启</span>")
        else:
            persist_txt = (f"　<span style='color:{MUTED}'>"
                           "开机自动重应用：未开启</span>")

        live = (self._live_state or {})
        live_mv = float(live.get("voltage_mv") or 0)
        target = int(live.get("clock_mhz") or 0) or self.spin_clock.value()

        curve = nvbackend.read_curve()
        ref_txt = ""
        if curve.get("ok") and curve.get("points"):
            near = min(curve["points"],
                       key=lambda pt: abs(pt[1] - target), default=None)
            if near:
                ref_txt = (f"　|　曲线参考：{target}MHz 附近为 "
                           f"<b>{near[0]} mV</b>")

        if live_mv > 0:
            live_txt = f"　|　实时电压 <b>{live_mv:.0f} mV</b>"
        else:
            live_txt = (f"　|　<span style='color:{MUTED}'>"
                        "实时电压不可读</span>")
        self.lbl_curve.setText(
            f"{applied_txt}{persist_txt}{live_txt}{ref_txt}")

    # ---------------- 操作 ----------------
    def shutdown(self) -> None:
        """关闭窗口前调用：停掉定时器并等待后台线程结束。

        若不等线程结束就销毁窗口，Qt 会在线程仍存活时释放对象，
        导致进程以 0xc0000409 异常退出。
        """
        try:
            self._live_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        # 注意：_power_worker 是守护线程封装（QObject），不参与 Qt 析构，
        # 这里不处理它，避免 terminate 阻塞中的 subprocess 造成崩溃。
        for attr in ("_live_worker", "_gpu_worker", "_worker", "_stress",
                     "_uv"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if w.isRunning():
                    w.quit()
                    if not w.wait(3000):
                        w.terminate()
                        w.wait(1000)
            except Exception:  # noqa: BLE001
                pass

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
        """自动搜索最低稳定电压（NVAPI 后端，无需 Afterburner）。"""
        if self._uv and self._uv.isRunning():
            return
        if not nvbackend.available():
            QMessageBox.warning(
                self, "不可用",
                "未找到 NVAPI 调参组件，无法进行降压搜索。")
            return
        freq = self.spin_clock.value()
        secs = self.spin_stress.value()
        step = float(self.spin_step.value())
        floor = float(self.spin_floor.value())
        transient = bool(self.check_transient.isChecked())

        st = nvbackend.status()
        start = float(st.get("mv") or 0) if st.get("ok") else 0.0
        if start <= 0:
            curve = nvbackend.read_curve()
            if curve.get("ok") and curve.get("points"):
                near = min(curve["points"],
                           key=lambda pt: abs(pt[1] - freq), default=None)
                if near:
                    start = float(near[0])
        if start <= 0:
            QMessageBox.warning(
                self, "无法开始",
                "无法确定起始电压。请先用「锁定频率」或直接在\n"
                "显卡驱动面板设一个已知稳定的电压，再执行搜索。")
            return

        est = max(1, int((start - floor) / step))
        msg = (
            f"目标频率：{freq} MHz\n"
            f"起始电压：{start:.0f} mV（当前已应用/曲线参考）\n"
            f"每档降压：-{step:.0f} mV，下限 {floor:.0f} mV\n"
            f"单档验证：{secs} 秒　"
            f"负载：{'瞬态（更接近游戏）' if transient else '恒定满载'}\n"
            f"预计最多 {est} 档（约 {est * (secs + 6) // 60} 分钟）\n\n"
            "流程：直接从 NVAPI 写入「电压上限 + 目标频率」→ 跑带数值校验\n"
            "的 PyTorch 负载 → 稳定就继续往下试，遇到第一档不稳定立即回退\n"
            "到上一档稳定值并停止。\n\n"
            "说明：每档 25mV 本身就是安全间距，最终停在的稳定档即建议值。\n"
            "搜索期间显卡会满载、温度上升，请勿同时运行游戏。\n\n"
            "开始后如果画面短暂黑屏属正常（电压不足时驱动会自恢复）。是否继续？")
        if QMessageBox.question(self, "自动搜索最低稳定电压", msg) != QMessageBox.Yes:
            return
        self.btn_uv_search.setEnabled(False)
        self.btn_uv_cancel.setEnabled(True)
        self.btn_uv_apply.setEnabled(False)
        self.progress.setValue(0)
        self._uv = NvUndervoltWorker(freq, secs, step, start, floor,
                                     transient=transient)
        self._uv.progress.connect(
            lambda m: self.progress.setFormat(m[:110]))
        self._uv.done.connect(self._on_undervolt)
        self._uv.start()

    def cancel_undervolt(self) -> None:
        if self._uv and self._uv.isRunning():
            self._uv.cancel()
            self.progress.setFormat("正在停止（会停在最后一个稳定档）…")

    def _on_undervolt(self, r: dict[str, Any]) -> None:
        self.btn_uv_search.setEnabled(True)
        self.btn_uv_cancel.setEnabled(False)
        self.progress.setFormat("降压搜索结束")
        self._last_uv = dict(r)

        rows = [("目标频率", f"{r.get('target_freq')} MHz"),
                ("起始电压", f"{r.get('start_mv', 0):.0f} mV"),
                ("最低稳定电压", f"{r.get('lowest_stable_mv', 0):.0f} mV"),
                ("建议使用电压", f"{r.get('suggested_mv', 0):.0f} mV"),
                ("后端", "NVAPI（无需 Afterburner）")]
        for a in r.get("attempts") or []:
            note = a.get("reason") or ""
            rows.append((f"  {a.get('attempt', 0):.0f} mV",
                         ("稳定" if a.get("ok") else "不稳定")
                         + (f"　满载{a['clock_avg']}MHz"
                            if a.get("clock_avg") else "")
                         + (f"　掉频{a['dropped']}次"
                            if a.get("dropped") else "")
                         + (f"　{note}" if note else "")))
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
        elif r.get("lowest_stable_mv"):
            QMessageBox.information(
                self, "降压完成",
                f"最低稳定电压：{r.get('lowest_stable_mv', 0):.0f} mV\n"
                f"建议使用：{r.get('suggested_mv', 0):.0f} mV\n"
                f"目标频率：{r.get('target_freq')} MHz\n\n"
                "点「一键应用并固化」写入并设为开机自动应用，\n"
                "之后就不再需要 Afterburner 了。\n\n"
                "建议随后用你常玩的游戏实测一段时间，确认无花屏/闪退。")
            self.btn_uv_apply.setEnabled(True)
        if self.notify:
            self.notify("GPU 降压完成",
                        f"{r.get('target_freq')}MHz @ "
                        f"{r.get('suggested_mv') or r.get('lowest_stable_mv', 0):.0f}mV")
        self.refresh()

    def apply_undervolt_preset(self) -> None:
        """把搜索结果写入 NVAPI 并持久化（开机自动重应用）。"""
        r = dict(self._last_uv or {})
        mv = float(r.get("suggested_mv") or r.get("lowest_stable_mv") or 0)
        freq = int(r.get("target_freq") or self.spin_clock.value())
        if mv <= 0:
            QMessageBox.information(
                self, "还没有结果",
                "请先运行一次「自动搜索最低稳定电压」。")
            return
        if QMessageBox.question(
                self, "应用并固化",
                f"把 {freq} MHz @ {mv:.0f} mV 写入显卡，\n"
                "并注册开机自动重应用？\n\n"
                "之后不需要 MSI Afterburner 也会自动生效。"
        ) != QMessageBox.Yes:
            return

        def work() -> dict[str, Any]:
            res = nvbackend.tune(freq, int(round(mv)), persist=True)
            res["target_freq"] = freq
            res["lowest_stable_mv"] = mv
            # 回读确认
            st = nvbackend.status()
            res["verify"] = st
            res["verify_ok"] = bool(st.get("ok") and not st.get("is_stock")
                                    and st.get("persists"))
            if res.get("ok") and not res["verify_ok"]:
                res["ok"] = False
                res["error"] = "写入后回读未确认生效，请检查显卡状态"
            return res

        self.btn_uv_apply.setEnabled(False)
        self._run("应用并固化 GPU 降压", work)

    def restore_curve(self) -> None:
        """恢复原厂：清空调参并移除开机任务。"""
        if QMessageBox.question(
                self, "恢复原厂",
                "清空所有电压/频率调参并移除开机自动应用？\n"
                "（显卡将回到厂商默认曲线）") != QMessageBox.Yes:
            return
        self._run("恢复原厂曲线", nvbackend.clear)

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
