"""硬件检测与测试页面：CPU / 内存 / 显存 / 风扇。

CPU-Z、MemTest86 都是专有软件，不可内嵌（见 docs\\licensing_notes.md）。
本页用自研实现达到等价效果：
  * CPU 信息（CPUID 类公开接口）
  * CPU 跑分（单核 / 多核）+ 全核压力测试
  * 内存信息（SMBIOS）+ Windows 级内存测试
  * 显存测试（内嵌开源 memtest_vulkan，zlib 许可）
  * 风扇能力检测（如实报告可用性）
"""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from . import cpubench, fan, hwinfo, memtest, vramtest

GOOD = "#2ec4a5"
WARN = "#ff9f43"
DANGER = "#f4577c"
MUTED = "#8d86a8"
TEXT = "#3a3352"
ACCENT = "#8b6cf6"


class Worker(QThread):
    done = Signal(str, dict)
    progress = Signal(str)

    def __init__(self, kind: str, fn: Callable[[Any], Any]) -> None:
        super().__init__()
        self.kind = kind
        self.fn = fn

    def run(self) -> None:
        try:
            r = self.fn(lambda m: self.progress.emit(m))
        except Exception as exc:  # noqa: BLE001
            r = {"error": str(exc)}
        self.done.emit(self.kind, r if isinstance(r, dict) else {"value": r})


class HardwarePage(QWidget):
    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.notify = notify
        self.set_status = status or (lambda _m: None)
        self._worker: QThread | None = None
        self._info: dict[str, Any] = {}
        self._build()
        # 延迟到事件循环启动后再检测；检测本身（hwinfo + 风扇探测）
        # 实测要 1 秒以上，必须放到后台线程，否则启动瞬间界面卡死。
        from PySide6.QtCore import QTimer
        QTimer.singleShot(400, self.refresh_info_async)
        # CPU 当前频率会随睿频/负载变化，单独定时刷新（1.5 秒一次）
        self._freq_timer = QTimer(self)
        self._freq_timer.setInterval(1500)
        self._freq_timer.timeout.connect(self._refresh_cpu_freq)
        self._freq_timer.start()
        # 调试用：允许直接定位到某个子页
        import os
        sub = os.environ.get("JUNKCLEANER_SUBTAB")
        if sub and sub.isdigit():
            idx = int(sub)
            if 0 <= idx < self.tabs.count():
                self.tabs.setCurrentIndex(idx)

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        self.lbl_sys = QLabel("读取中…")
        self.lbl_sys.setWordWrap(True)
        top.addWidget(self.lbl_sys, 1)
        self.btn_refresh = QPushButton("重新检测")
        self.btn_refresh.setObjectName("Ghost")
        self.btn_refresh.clicked.connect(self.refresh_info)
        top.addWidget(self.btn_refresh)
        lay.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_cpu(), "CPU")
        self.tabs.addTab(self._tab_memory(), "内存")
        self.tabs.addTab(self._tab_vram(), "显存")
        self.tabs.addTab(self._tab_fan(), "风扇")
        lay.addWidget(self.tabs, 1)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        lay.addWidget(self.progress)

    # ---------------- CPU 页 ----------------
    def _tab_cpu(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(9)

        info_box = QGroupBox("CPU 信息")
        g = QGridLayout(info_box)
        self.cpu_fields: dict[str, QLabel] = {}
        rows = [("name", "型号"), ("vendor", "厂商"), ("cores", "核心 / 线程"),
                ("cache", "二级 / 三级缓存"), ("freq", "频率（当前 / 基准 / 最大）"),
                ("feat", "指令集"), ("micro", "微码")]
        for i, (key, label) in enumerate(rows):
            name = QLabel(label)
            name.setObjectName("Muted")
            val = QLabel("—")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setWordWrap(True)
            self.cpu_fields[key] = val
            g.addWidget(name, i, 0)
            g.addWidget(val, i, 1)
        g.setColumnStretch(1, 1)
        lay.addWidget(info_box)

        bench_box = QGroupBox("跑分与压力测试")
        b = QHBoxLayout(bench_box)
        self.btn_bench = QPushButton("开始跑分")
        self.btn_bench.setObjectName("Primary")
        self.btn_bench.clicked.connect(self.run_bench)
        self.btn_stress = QPushButton("全核压力测试")
        self.btn_stress.clicked.connect(self.run_cpu_stress)
        self.spin_stress = QSpinBox()
        self.spin_stress.setRange(10, 1800)
        self.spin_stress.setValue(60)
        self.spin_stress.setSuffix(" 秒")
        b.addWidget(self.btn_bench)
        b.addWidget(self.btn_stress)
        b.addWidget(self.spin_stress)
        b.addStretch(1)
        lay.addWidget(bench_box)

        self.result = QTableWidget(0, 2)
        self.result.setHorizontalHeaderLabels(["项目", "结果"])
        self.result.verticalHeader().setVisible(False)
        self.result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.result.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        self.result.setColumnWidth(0, 200)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.result, 1)
        return page

    # ---------------- 内存页 ----------------
    def _tab_memory(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(9)

        self.mem_label = QLabel("读取中…")
        self.mem_label.setWordWrap(True)
        lay.addWidget(self.mem_label)

        self.dimm_table = QTableWidget(0, 6)
        self.dimm_table.setHorizontalHeaderLabels(
            ["插槽", "容量", "频率", "厂商", "型号", "电压"])
        self.dimm_table.verticalHeader().setVisible(False)
        self.dimm_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.dimm_table.horizontalHeader()
        for i, w in enumerate([130, 80, 90, 120]):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.dimm_table.setColumnWidth(i, w)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.Fixed)
        self.dimm_table.setColumnWidth(5, 90)
        self.dimm_table.setMaximumHeight(140)
        lay.addWidget(self.dimm_table)

        test_box = QGroupBox("内存稳定性测试")
        t = QGridLayout(test_box)
        self.lbl_mem_note = QLabel(
            "说明：Windows 运行时无法测试系统自身占用的内存。"
            "要覆盖全部物理内存需从 U 盘启动 MemTest86+。")
        self.lbl_mem_note.setWordWrap(True)
        self.lbl_mem_note.setStyleSheet(f"color:{WARN}")
        t.addWidget(self.lbl_mem_note, 0, 0, 1, 5)
        self.spin_mem_mb = QSpinBox()
        self.spin_mem_mb.setRange(64, 32768)
        self.spin_mem_mb.setSingleStep(256)
        self.spin_mem_mb.setValue(2048)
        self.spin_mem_mb.setSuffix(" MB")
        self.spin_mem_rounds = QSpinBox()
        self.spin_mem_rounds.setRange(1, 100)
        self.spin_mem_rounds.setValue(1)
        self.spin_mem_rounds.setSuffix(" 轮")
        self.btn_mem = QPushButton("开始内存测试")
        self.btn_mem.setObjectName("Primary")
        self.btn_mem.clicked.connect(self.run_memtest)
        self.btn_mem_stop = QPushButton("停止")
        self.btn_mem_stop.setObjectName("Danger")
        self.btn_mem_stop.setEnabled(False)
        self.btn_mem_stop.clicked.connect(self.stop_memtest)
        t.addWidget(QLabel("测试容量"), 1, 0)
        t.addWidget(self.spin_mem_mb, 1, 1)
        t.addWidget(QLabel("轮数"), 1, 2)
        t.addWidget(self.spin_mem_rounds, 1, 3)
        t.addWidget(self.btn_mem, 1, 4)
        t.addWidget(self.btn_mem_stop, 2, 4)
        lay.addWidget(test_box)

        self.mem_result = QTableWidget(0, 2)
        self.mem_result.setHorizontalHeaderLabels(["项目", "结果"])
        self.mem_result.verticalHeader().setVisible(False)
        self.mem_result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        mh = self.mem_result.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.mem_result.setColumnWidth(0, 200)
        mh.setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.mem_result, 1)
        return page

    # ---------------- 显存页 ----------------
    def _tab_vram(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(9)

        info = QLabel(
            "显存稳定性测试（内嵌开源工具 memtest_vulkan，zlib 许可）。\n"
            "它会反复写入并校验显存内容，能发现显存超频/老化导致的位错误——"
            "这类错误常表现为游戏花屏或贴图异常，普通满载压测测不出来。\n"
            "建议至少跑 6 分钟；测试期间请勿运行游戏或 3D 程序。")
        info.setObjectName("Muted")
        info.setWordWrap(True)
        lay.addWidget(info)

        ctl = QGroupBox("测试设置")
        g = QGridLayout(ctl)
        self.spin_vram_min = QSpinBox()
        self.spin_vram_min.setRange(1, 120)
        self.spin_vram_min.setValue(6)
        self.spin_vram_min.setSuffix(" 分钟")
        self.spin_vram_min.setToolTip("建议至少 6 分钟；时间越长越容易暴露偶发错误")
        self.btn_vram = QPushButton("开始显存测试")
        self.btn_vram.setObjectName("Primary")
        self.btn_vram.clicked.connect(self.run_vramtest)
        self.btn_vram_stop = QPushButton("停止")
        self.btn_vram_stop.setObjectName("Danger")
        self.btn_vram_stop.setEnabled(False)
        self.btn_vram_stop.clicked.connect(self.stop_vramtest)
        self.lbl_vram_status = QLabel("未测试")
        self.lbl_vram_status.setWordWrap(True)
        g.addWidget(QLabel("测试时长"), 0, 0)
        g.addWidget(self.spin_vram_min, 0, 1)
        g.addWidget(self.btn_vram, 0, 2)
        g.addWidget(self.btn_vram_stop, 0, 3)
        g.addWidget(self.lbl_vram_status, 1, 0, 1, 4)
        lay.addWidget(ctl)

        self.vram_result = QTableWidget(0, 2)
        self.vram_result.setHorizontalHeaderLabels(["项目", "结果"])
        self.vram_result.verticalHeader().setVisible(False)
        self.vram_result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        vh = self.vram_result.horizontalHeader()
        vh.setSectionResizeMode(0, QHeaderView.Fixed)
        self.vram_result.setColumnWidth(0, 200)
        vh.setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.vram_result, 1)
        return page

    # ---------------- 风扇页 ----------------
    def _tab_fan(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(9)

        cg = QGroupBox("CPU / 主板风扇")
        c = QVBoxLayout(cg)
        self.lbl_cpu_fan = QLabel("检测中…")
        self.lbl_cpu_fan.setWordWrap(True)
        self.lbl_cpu_fan.setTextFormat(Qt.RichText)
        c.addWidget(self.lbl_cpu_fan)
        lay.addWidget(cg)

        gg = QGroupBox("GPU 风扇")
        g = QVBoxLayout(gg)
        self.lbl_gpu_fan = QLabel("检测中…")
        self.lbl_gpu_fan.setWordWrap(True)
        self.lbl_gpu_fan.setTextFormat(Qt.RichText)
        g.addWidget(self.lbl_gpu_fan)
        self.btn_ab = QPushButton("检测 / 打开 MSI Afterburner")
        self.btn_ab.setObjectName("Ghost")
        self.btn_ab.clicked.connect(self.open_afterburner)
        g.addWidget(self.btn_ab, 0, Qt.AlignLeft)

        ab_row = QHBoxLayout()
        self.btn_ab_install = QPushButton("一键下载并安装 Afterburner")
        self.btn_ab_install.setObjectName("Primary")
        self.btn_ab_install.clicked.connect(self.install_afterburner)
        self.btn_ab_page = QPushButton("打开官方下载页")
        self.btn_ab_page.setObjectName("Ghost")
        self.btn_ab_page.clicked.connect(self.open_afterburner)
        self.lbl_ab_bundle = QLabel("")
        self.lbl_ab_bundle.setWordWrap(True)
        self.lbl_ab_bundle.setTextFormat(Qt.RichText)
        g.addWidget(self.lbl_ab_bundle)
        ab_row.addWidget(self.btn_ab_install)
        ab_row.addWidget(self.btn_ab_page)
        ab_row.addStretch(1)
        g.addLayout(ab_row)
        lay.addWidget(gg)

        curve_box = QGroupBox("GPU 风扇温度曲线（本环境不可用时仅作规划）")
        cv = QGridLayout(curve_box)
        self.curve_label = QLabel(
            "默认曲线：" + "　".join(
                f"{t}°C→{p}%" for t, p in fan.DEFAULT_CURVE))
        self.curve_label.setWordWrap(True)
        cv.addWidget(self.curve_label, 0, 0, 1, 4)
        self.spin_fixed = QSpinBox()
        self.spin_fixed.setRange(0, 100)
        self.spin_fixed.setValue(60)
        self.spin_fixed.setSuffix(" %")
        self.btn_fixed = QPushButton("固定转速")
        self.btn_fixed.setObjectName("Ghost")
        self.btn_fixed.clicked.connect(self.set_fixed_fan)
        self.btn_auto = QPushButton("恢复自动")
        self.btn_auto.setObjectName("Ghost")
        self.btn_auto.clicked.connect(self.set_auto_fan)
        cv.addWidget(QLabel("固定档"), 1, 0)
        cv.addWidget(self.spin_fixed, 1, 1)
        cv.addWidget(self.btn_fixed, 1, 2)
        cv.addWidget(self.btn_auto, 1, 3)
        lay.addWidget(curve_box)
        lay.addStretch(1)
        return page

    # ---------------- 数据 ----------------
    def shutdown(self) -> None:
        """关闭窗口前停止定时器并等待后台线程（避免退出时崩溃）。"""
        try:
            self._freq_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        if hasattr(self, "_vram_timer"):
            try:
                self._vram_timer.stop()
            except Exception:  # noqa: BLE001
                pass
        for attr in ("_worker",):
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
        t = getattr(self, "_vram", None)
        if t is not None:
            try:
                t.stop()
            except Exception:  # noqa: BLE001
                pass

    def _refresh_cpu_freq(self) -> None:
        """定时刷新 CPU 当前频率（睿频会变，基准频率不会）。"""
        try:
            cpu = (self._info or {}).get("cpu") or {}
            base = cpu.get("base_mhz") or 0
            mx = cpu.get("max_mhz") or 0
            if not base:
                return
            cur = hwinfo.current_freq_mhz()
            if not cur:
                return
            cpu["current_mhz"] = cur
            self.cpu_fields["freq"].setText(
                f"当前 <b>{cur} MHz</b>　基准 {base} MHz　最大 {mx} MHz")
        except Exception:  # noqa: BLE001
            pass

    def refresh_info(self) -> None:
        import json
        self.lbl_sys.setText("正在检测硬件…")
        try:
            self._info = hwinfo.collect_all()
        except Exception as exc:  # noqa: BLE001
            self.lbl_sys.setText(f"检测失败：{exc}")
            return
        self._render_info()

    def refresh_info_async(self) -> None:
        """后台执行硬件检测（collect_all + 风扇探测约 1 秒以上）。"""
        if self._worker and self._worker.isRunning():
            return
        self.lbl_sys.setText("正在检测硬件…")

        def work(_progress: Any = None) -> dict:
            # 风扇探测（fan.status）实测要 300ms 以上，一并放到后台，
            # 否则检测完成回填时会卡住主线程。
            return {"info": hwinfo.collect_all(), "fan": fan.status()}

        self._worker = Worker("硬件检测", work)
        self._worker.done.connect(self._on_info_loaded)
        self._worker.start()

    def _on_info_loaded(self, _kind: str, r: dict) -> None:
        if r.get("error"):
            self.lbl_sys.setText(f"检测失败：{r['error']}")
            return
        self._info = r.get("info") or {}
        self._fan_status = r.get("fan") or {}
        self._render_info()

    def _render_info(self) -> None:
        """把已取得的硬件信息渲染到界面（主线程，纯 UI 操作）。"""
        cpu = self._info.get("cpu", {})
        board = self._info.get("board", {})
        self.lbl_sys.setText(
            f"<b>{cpu.get('name','')}</b>　"
            f"{board.get('board_vendor','')} {board.get('board_name','')}　"
            f"BIOS {board.get('bios_version','')}（{board.get('bios_date','')}）")

        f = self.cpu_fields
        f["name"].setText(cpu.get("name", ""))
        f["vendor"].setText(f"{cpu.get('vendor','')}　"
                            f"ID {cpu.get('identifier','')}")
        f["cores"].setText(f"{cpu.get('cores')} 核 / {cpu.get('threads')} 线程"
                           f"　{cpu.get('architecture','')}")
        f["cache"].setText(f"L2 {cpu.get('l2_kb',0)//1024} MB ／ "
                           f"L3 {cpu.get('l3_kb',0)//1024} MB")
        base = cpu.get("base_mhz") or 0
        mx = cpu.get("max_mhz") or 0
        cur = cpu.get("current_mhz") or 0
        cur_txt = f"<b>{cur} MHz</b>" if cur else "—"
        f["freq"].setText(
            f"当前 {cur_txt}　基准 {base} MHz　最大 {mx} MHz")
        self._cpu_clock_base = cur or base
        f["feat"].setText("、".join(cpu.get("features") or []) or "—")
        f["micro"].setText(cpu.get("microcode") or "—")

        dimms = self._info.get("memory") or []
        total = sum(d.get("capacity_gb", 0) for d in dimms)
        speeds = {d.get("configured_mhz") or d.get("speed_mhz") for d in dimms}
        self.mem_label.setText(
            f"共 <b>{total:.0f} GB</b>，{len(dimms)} 条　"
            f"运行频率 {', '.join(str(s) for s in sorted(speeds) if s)} MHz　"
            f"（容量/频率来自 SMBIOS）")
        self.dimm_table.setRowCount(len(dimms))
        for i, d in enumerate(dimms):
            self.dimm_table.setItem(i, 0, QTableWidgetItem(str(d.get("slot", ""))))
            self.dimm_table.setItem(i, 1, QTableWidgetItem(
                f"{d.get('capacity_gb', 0):.0f} GB"))
            self.dimm_table.setItem(i, 2, QTableWidgetItem(
                f"{d.get('configured_mhz') or d.get('speed_mhz')} MHz"))
            self.dimm_table.setItem(i, 3, QTableWidgetItem(
                str(d.get("manufacturer", ""))))
            self.dimm_table.setItem(i, 4, QTableWidgetItem(
                str(d.get("part_number", ""))))
            self.dimm_table.setItem(i, 5, QTableWidgetItem(
                f"{d.get('voltage_mv', 0)} mV"
                if d.get("voltage_mv") else "—"))

        self._render_fan()
        self.set_status("硬件检测完成")

    def _render_fan(self) -> None:
        # 优先使用后台线程取回的结果；没有则回退到同步调用
        # （异步路径已在 _on_info_loaded 里预取，正常不会走到这里）
        s = getattr(self, "_fan_status", None) or fan.status()
        cpu = s["cpu"]
        lines = [f"<b>可读性：</b>{'可以' if cpu.get('readable') else '不可以'}"
                 f"　检测到风扇 {cpu.get('fan_count', 0)} 个"]
        if cpu.get("reasons"):
            lines.append(f"<span style='color:{DANGER}'>原因：</span>"
                         + "；".join(cpu["reasons"]))
        if cpu.get("requires"):
            lines.append(f"<span style='color:{MUTED}'>可行路径：</span>")
            lines.append("<ul style='margin:2px 0 0 16px'>"
                         + "".join(f"<li>{x}</li>" for x in cpu["requires"])
                         + "</ul>")
        self.lbl_cpu_fan.setText("<br>".join(lines))

        g = s["gpu"]
        gl = [f"<b>驱动：</b>{g.get('driver','')}　"
              f"当前风扇 {g.get('current_percent','—')}%",
              f"<b>NVAPI 可调用：</b>"
              f"{'是' if g.get('nvapi_callable') else '否'}"]
        if g.get("reason"):
            gl.append(f"<span style='color:{WARN}'>{g['reason']}</span>")
        if g.get("alternatives"):
            gl.append("<span style='color:{0}'>替代方案：</span>".format(MUTED))
            gl.append("<ul style='margin:2px 0 0 16px'>"
                      + "".join(f"<li>{x}</li>" for x in g["alternatives"])
                      + "</ul>")
        self.lbl_gpu_fan.setText("<br>".join(gl))
        if hasattr(self, "lbl_ab_bundle"):
            self.lbl_ab_bundle.setText(self._ab_bundle_hint())
        # 不可用时禁用按钮
        usable = bool(g.get("controllable"))
        self.btn_fixed.setEnabled(usable)
        self.btn_auto.setEnabled(usable)

    # ---------------- 操作 ----------------
    def run_bench(self) -> None:
        self._start("CPU 跑分", cpubench.benchmark, self._on_bench)

    def _on_bench(self, r: dict[str, Any]) -> None:
        rows = [
            ("单核得分", f"{r.get('single_score', 0):.1f}"),
            ("多核得分", f"{r.get('multi_score', 0):.1f}"),
            ("多核倍率", f"{r.get('ratio', 0):.2f} x（{r.get('threads')} 线程）"),
            ("单核耗时", f"{r.get('single_seconds', 0):.3f} s"),
            ("多核耗时", f"{r.get('multi_seconds', 0):.3f} s"),
            ("说明", r.get("note") or "分数为每秒千次迭代，越高越快"),
        ]
        self._fill(self.result, rows)

    def run_cpu_stress(self) -> None:
        secs = self.spin_stress.value()
        if QMessageBox.question(
                self, "CPU 压力测试",
                f"全核满载 {secs} 秒？期间 CPU 会 100% 占满，"
                "请勿同时进行重要工作。") != QMessageBox.Yes:
            return
        self._start(f"CPU 压力测试 {secs}s",
                    lambda p: cpubench.cpu_stress(seconds=secs, progress=p),
                    self._on_stress)

    def _on_stress(self, r: dict[str, Any]) -> None:
        if r.get("error"):
            self._fill(self.result, [("错误", r["error"])])
            return
        rows = [
            ("负载", f"平均 {r.get('load_avg')}%（最低 {r.get('load_min')}%）"),
            ("线程数", str(r.get("threads"))),
            ("温度", f"最高 {r.get('temp_max')}°C / 平均 {r.get('temp_avg')}°C"),
            ("频率", f"{r.get('clock_min')} ~ {r.get('clock_max')} MHz"),
            ("采样点", str(r.get("samples"))),
            ("结论", "全核满载稳定，无异常降频"
             if r.get("load_min", 0) >= 95 else "存在负载不足，建议重测"),
        ]
        self._fill(self.result, rows)
        if self.notify:
            self.notify("CPU 压力测试完成",
                        f"{r.get('seconds')}s，最高 {r.get('temp_max')}°C")

    def run_memtest(self) -> None:
        mb = self.spin_mem_mb.value()
        rounds = self.spin_mem_rounds.value()
        if QMessageBox.question(
                self, "内存测试",
                f"测试 {mb} MB 空闲内存，{rounds} 轮？\n\n"
                "注意：Windows 运行时无法测试系统自身占用的内存，"
                "要全覆盖需从 U 盘启动 MemTest86+。") != QMessageBox.Yes:
            return
        self.btn_mem.setEnabled(False)
        self.btn_mem_stop.setEnabled(True)
        self._tester = memtest.MemTester(
            alloc_mb=mb, rounds=rounds,
            progress=lambda m: self.progress.setFormat(m[:110]))
        self._worker = Worker("内存测试", lambda p: self._tester.run().to_dict())
        self._worker.done.connect(self._on_memtest)
        self._worker.start()

    def stop_memtest(self) -> None:
        if getattr(self, "_tester", None):
            self._tester.cancel()
            self.progress.setFormat("正在停止内存测试…")

    # ---------------- 显存测试 ----------------
    def run_vramtest(self) -> None:
        if not vramtest.available():
            QMessageBox.warning(
                self, "不可用",
                "未找到内嵌的 memtest_vulkan.exe，无法进行显存测试。")
            return
        minutes = self.spin_vram_min.value()
        if QMessageBox.question(
                self, "显存测试",
                f"开始显存稳定性测试，时长约 {minutes} 分钟？\n\n"
                "测试会持续满载显存并逐字节校验，期间请勿运行游戏或\n"
                "3D 程序。可随时点「停止」，但未跑完时结论不完整。\n\n"
                "该功能用于排查花屏/贴图异常是否由显存不稳引起。"
        ) != QMessageBox.Yes:
            return
        self._vram = vramtest.VramTest()
        r = self._vram.start()
        if not r.get("ok"):
            QMessageBox.warning(self, "启动失败", str(r.get("error")))
            return
        self._vram_deadline = time.time() + minutes * 60
        self.btn_vram.setEnabled(False)
        self.btn_vram_stop.setEnabled(True)
        self.vram_result.setRowCount(0)
        self.lbl_vram_status.setText("测试中…")
        if not hasattr(self, "_vram_timer"):
            self._vram_timer = QTimer(self)
            self._vram_timer.setInterval(1000)
            self._vram_timer.timeout.connect(self._poll_vramtest)
        self._vram_timer.start()

    def _poll_vramtest(self) -> None:
        t = getattr(self, "_vram", None)
        if t is None:
            return
        snap = t.poll()
        elapsed_ok = time.time() >= getattr(self, "_vram_deadline", 0)
        self.lbl_vram_status.setText(
            f"运行中：{snap['device'] or '正在识别显卡'}　"
            f"迭代 {snap['iterations']}　"
            f"已校验 {snap['checked_gb']}GB　"
            f"{snap['speed_gb_s']}GB/s　"
            f"错误 {snap['error_count']}")
        self.progress.setFormat(
            f"显存测试：迭代 {snap['iterations']}　"
            f"校验 {snap['checked_gb']}GB")
        if snap["error_count"]:
            self.lbl_vram_status.setText(
                f"<span style='color:{DANGER}'>检出显存错误！</span>　"
                f"迭代 {snap['iterations']}　"
                f"已校验 {snap['checked_gb']}GB")
        # 到达设定时长 或 已得出结论 或 进程意外退出 → 收尾
        if elapsed_ok or snap["finished"] or not snap["running"]:
            if elapsed_ok and snap["running"]:
                t.stop()
            self._finish_vramtest()

    def _finish_vramtest(self) -> None:
        if hasattr(self, "_vram_timer"):
            self._vram_timer.stop()
        t = getattr(self, "_vram", None)
        self.btn_vram.setEnabled(True)
        self.btn_vram_stop.setEnabled(False)
        if t is None:
            return
        snap = t.summary()
        self._render_vram_result(snap)

    def stop_vramtest(self) -> None:
        t = getattr(self, "_vram", None)
        if t and t.running:
            self.progress.setFormat("正在停止显存测试…")
            self._finish_vramtest()

    def _render_vram_result(self, snap: dict) -> None:
        passed = snap.get("passed")
        if passed is True:
            verdict, color = "未发现显存错误", GOOD
        elif passed is False:
            verdict, color = "检出显存错误", DANGER
        elif snap.get("stopped_by_user"):
            verdict, color = "已停止（结论不完整）", WARN
        else:
            verdict, color = "尚未得出结果", MUTED
        self.lbl_vram_status.setText(
            f"<span style='color:{color};font-weight:700'>{verdict}</span>")
        rows = [
            ("显卡", snap.get("device") or "—"),
            ("结论", verdict),
            ("迭代次数", str(snap.get("iterations", 0))),
            ("写入显存", f"{snap.get('written_gb', 0):.1f} GB"),
            ("校验显存", f"{snap.get('checked_gb', 0):.1f} GB"),
            ("峰值带宽", f"{snap.get('speed_gb_s', 0):.1f} GB/s"),
            ("错误条数", str(snap.get("error_count", 0))),
        ]
        for e in snap.get("errors") or []:
            rows.append(("错误详情", e))
        self.vram_result.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.vram_result.setItem(i, 0, QTableWidgetItem(str(k)))
            item = QTableWidgetItem(str(v))
            if k == "结论":
                item.setForeground(Qt.darkGreen if passed is True
                                   else (Qt.red if passed is False
                                         else Qt.darkYellow))
            self.vram_result.setItem(i, 1, item)
        self.progress.setFormat("显存测试结束")
        if self.notify:
            self.notify("显存测试完成", verdict)

    def _on_memtest(self, _kind: str, r: dict[str, Any]) -> None:
        self.btn_mem.setEnabled(True)
        self.btn_mem_stop.setEnabled(False)
        self.progress.setFormat("内存测试完成")
        errs = r.get("error_count", 0)
        rows = [
            ("测试容量", f"{r.get('alloc_mb')} MB"),
            ("扫描总量", f"{r.get('bytes_scanned', 0) / (1 << 30):.2f} GB × 校验"),
            ("耗时", f"{r.get('seconds')} s"),
            ("错误数", str(errs)),
            ("系统内存", f"总 {r.get('total_ram_gb')} GB / "
                         f"空闲 {r.get('free_ram_gb')} GB"),
            ("结论", "通过（未发现错误）" if r.get("passed")
             else ("已取消" if r.get("cancelled") else "发现问题，请核查")),
            ("限制说明", r.get("note", "")),
        ]
        self._fill(self.mem_result, rows)
        if errs and self.notify:
            self.notify("内存测试发现错误", f"共 {errs} 个错误")

    def set_fixed_fan(self) -> None:
        f = fan.NvFan()
        r = f.set_percent(self.spin_fixed.value())
        if r.get("ok"):
            self.set_status(f"GPU 风扇已设为 {r.get('percent')}%")
        else:
            QMessageBox.warning(self, "风扇设置失败",
                                str(r.get("error") or r.get("rc")))
        self._render_fan()

    def set_auto_fan(self) -> None:
        f = fan.NvFan()
        r = f.set_auto()
        if not r.get("ok"):
            QMessageBox.warning(self, "恢复自动失败",
                                str(r.get("error") or r.get("rc")))
        self._render_fan()

    def open_afterburner(self) -> None:
        """检测 Afterburner；没装则给出明确说明（不内嵌专有软件）。"""
        from . import vfcurve
        d = vfcurve.find_afterburner()
        if d:
            QMessageBox.information(
                self, "已找到 MSI Afterburner",
                f"路径：{d}\n\n"
                "降压调优与风扇曲线都可以通过它工作。\n"
                "（Afterburner 自带 RTCore 内核驱动，"
                "这是 NVIDIA 新驱动下唯一可行的用户态控制通道。）")
            try:
                import os
                os.startfile(str(d / "MSIAfterburner.exe"))
            except OSError:
                pass
            return
        QMessageBox.information(
            self, "未检测到 MSI Afterburner",
            "未找到 MSI Afterburner。\n\n"
            "点「一键下载并安装」会自动完成；\n"
            "若自动下载被 CDN 拦截，会打开官方下载页让你手动下载，\n"
            f"下载后把安装包放到：\n{self._ab_drop_hint()}\n"
            "再回到本页点「检测」，本工具会自动校验并静默安装。\n\n"
            "注意：MSI 官方页面上的下载按钮实际指向 Norton 推广包，"
            "本工具会校验并拒绝它，不会把 Norton 装进你的电脑。")

    def _ab_drop_hint(self) -> str:
        from . import afterburner as _ab
        return str(_ab.download_dir())

    def _ab_bundle_hint(self) -> str:
        from . import afterburner as _ab
        b = _ab.bundled_zip()
        if b:
            return (f"<span style='color:{GOOD}'>✔ 程序内嵌了安装包</span>"
                    f"（{b.name}），点按钮即可离线安装。")
        return (f"<span style='color:{MUTED}'>本版本未内嵌安装包</span>；"
                "点按钮会先尝试联网获取，失败则引导手动下载。")

    def install_afterburner(self) -> None:
        """一键下载并静默安装 Afterburner（含严格校验）。"""
        from . import afterburner as _ab
        if _ab.is_installed():
            QMessageBox.information(self, "已安装",
                                    f"Afterburner 已存在：\n{_ab.find()}")
            self._render_fan()
            return
        drop = _ab.download_dir()
        local = _ab.scan_manual_drop()
        msg = (f"将从 MSI 官方渠道下载并静默安装 MSI Afterburner 到：\n"
               f"{_ab.install_dir() / 'runtime' / 'MSI Afterburner'}\n\n"
               "下载内容会做校验：确认为真正的 Afterburner 才安装；\n"
               "如果拿到的是 Norton 推广包会被拒绝。\n\n")
        if local.get("ok"):
            msg += f"已发现本地安装包（{local['file']}），将直接使用它。\n"
        msg += "\n继续吗？"
        if QMessageBox.question(self, "安装 Afterburner", msg) != QMessageBox.Yes:
            return
        if self._worker and self._worker.isRunning():
            return
        self.btn_ab_install.setEnabled(False)
        self.progress.setFormat("正在安装 Afterburner…")

        def work(prog):
            r = _ab.full_install(prog)
            if not r.get("ok"):
                r["drop_dir"] = str(drop)
            return r

        self._worker = Worker("安装 Afterburner", work)
        self._worker.progress.connect(
            lambda m: self.progress.setFormat(m[:110]))
        self._worker.done.connect(self._on_ab_install)
        self._worker.start()

    def _on_ab_install(self, _kind: str, r: dict) -> None:
        self.btn_ab_install.setEnabled(True)
        if r.get("ok"):
            self.progress.setFormat("Afterburner 安装完成")
            QMessageBox.information(
                self, "完成",
                f"Afterburner 已安装：\n{r.get('path') or r.get('already')}\n\n"
                "降压调优功能已解锁。")
            if self.notify:
                self.notify("Afterburner 已就绪", "GPU 降压功能已解锁")
        else:
            self.progress.setFormat("安装未完成")
            hint = r.get("hint") or r.get("error") or r.get("detail") or "未知错误"
            errs = r.get("errors") or []
            extra = ("\n\n失败原因：\n  " + "\n  ".join(str(e)[:90]
                     for e in errs[:3])) if errs else ""
            QMessageBox.warning(
                self, "需要手动下载",
                f"自动获取未成功：\n{hint}{extra}\n\n"
                f"请点「打开官方下载页」下载 Afterburner，\n"
                f"然后把安装包放到：\n{r.get('drop_dir', self._ab_drop_hint())}\n"
                "再回到本页点「一键下载并安装」，会自动校验并静默安装。")
        self._render_fan()

    # ---------------- 工具 ----------------
    def _start(self, kind: str, fn: Callable[..., Any],
               on_done: Callable[[dict[str, Any]], None]) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.progress.setFormat(f"{kind}…")
        self._worker = Worker(kind, fn)
        self._worker.progress.connect(
            lambda m: self.progress.setFormat(m[:110]))
        self._worker.done.connect(lambda k, r: on_done(r))
        self._worker.start()

    def _fill(self, table: QTableWidget,
              rows: list[tuple[str, str]]) -> None:
        table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(str(k)))
            table.setItem(i, 1, QTableWidgetItem(str(v)))
