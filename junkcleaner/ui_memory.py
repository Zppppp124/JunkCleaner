"""内存检测与释放页面（淡紫可爱风）。"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QProgressBar, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import core, memory

PURPLE = "#7c5cff"
PURPLE_DEEP = "#5b3fd6"
PURPLE_SOFT = "#efe9ff"
MINT = "#2ec4b6"
CORAL = "#ff6b81"
INK = "#2f2a45"
MUTED = "#8a83a8"


class RingWidget(QWidget):
    """可爱风环形内存占用图。"""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(190, 190)
        self._percent = 0.0
        self._used = 0
        self._total = 0

    def set_value(self, percent: float, used: int, total: int) -> None:
        self._percent = max(0.0, min(100.0, percent))
        self._used = used
        self._total = total
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 18
        rect = self.rect()
        p.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
        width = max(12, side // 11)
        pen = QPen(QColor(PURPLE_SOFT), width)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(width // 2, width // 2, side - width, side - width,
                  90 * 16, -360 * 16)
        color = QColor(MINT)
        if self._percent >= 85:
            color = QColor(CORAL)
        elif self._percent >= 65:
            color = QColor("#ffb703")
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        span = int(-360 * 16 * (self._percent / 100.0))
        p.drawArc(width // 2, width // 2, side - width, side - width, 90 * 16, span)

        p.setPen(QColor(INK))
        f = QFont("Microsoft YaHei UI", 26, QFont.Bold)
        p.setFont(f)
        p.drawText(0, int(side * 0.36), side, int(side * 0.3),
                   Qt.AlignCenter, f"{self._percent:.0f}%")
        p.setPen(QColor(MUTED))
        p.setFont(QFont("Microsoft YaHei UI", 10))
        p.drawText(0, int(side * 0.55), side, int(side * 0.2),
                   Qt.AlignCenter,
                   f"{core.human_size(self._used)} / {core.human_size(self._total)}")


class ReleaseWorker(QThread):
    done = Signal(dict)
    step = Signal(str)

    def __init__(self, level: str) -> None:
        super().__init__()
        self.level = level

    def run(self) -> None:
        result = memory.release(level=self.level,
                                progress=lambda name: self.step.emit(name))
        self.done.emit(result.to_dict())


class MemoryPage(QWidget):
    """内存检测 / 一键释放 / 自动释放。"""

    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.notify = notify
        self.set_status = status or (lambda _m: None)
        self._worker: ReleaseWorker | None = None
        self._autoreleaser = memory.AutoReleaser(notify=notify)
        self._build()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(14)

        ring_box = QFrame()
        ring_box.setObjectName("Card")
        rb = QVBoxLayout(ring_box)
        rb.setContentsMargins(16, 14, 16, 14)
        self.ring = RingWidget()
        rb.addWidget(self.ring, 0, Qt.AlignCenter)
        self.lbl_hint = QLabel("内存状态良好")
        self.lbl_hint.setAlignment(Qt.AlignCenter)
        self.lbl_hint.setObjectName("H2")
        rb.addWidget(self.lbl_hint)
        top.addWidget(ring_box, 1)

        info_box = QGroupBox("内存详情")
        grid = QGridLayout(info_box)
        grid.setVerticalSpacing(9)
        self.lbl_total = self._metric(grid, 0, "物理内存总量")
        self.lbl_used = self._metric(grid, 1, "已使用")
        self.lbl_avail = self._metric(grid, 2, "可用")
        self.lbl_cached = self._metric(grid, 3, "系统缓存")
        self.lbl_commit = self._metric(grid, 4, "已提交")
        self.lbl_procs = self._metric(grid, 5, "进程 / 线程")
        top.addWidget(info_box, 1)

        act_box = QGroupBox("释放工具")
        ab = QVBoxLayout(act_box)
        ab.setSpacing(9)
        row = QHBoxLayout()
        self.cmb_level = QComboBox()
        self.cmb_level.addItem("温和（仅修剪工作集）", "gentle")
        self.cmb_level.addItem("标准（推荐）", "standard")
        self.cmb_level.addItem("深度（清缓存）", "deep")
        self.cmb_level.setCurrentIndex(1)
        row.addWidget(QLabel("力度"))
        row.addWidget(self.cmb_level, 1)
        ab.addLayout(row)
        self.btn_release = QPushButton("一键释放内存")
        self.btn_release.setObjectName("Primary")
        self.btn_release.setMinimumHeight(42)
        self.btn_release.clicked.connect(self.release_now)
        ab.addWidget(self.btn_release)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("Ghost")
        self.btn_refresh.clicked.connect(self.refresh)
        ab.addWidget(self.btn_refresh)
        self.lbl_result = QLabel("")
        self.lbl_result.setObjectName("Muted")
        self.lbl_result.setWordWrap(True)
        ab.addWidget(self.lbl_result)
        ab.addStretch(1)
        top.addWidget(act_box, 1)
        lay.addLayout(top)

        auto_box = QGroupBox("自动释放")
        ag = QGridLayout(auto_box)
        self.chk_auto = QCheckBox("内存占用超过阈值时自动释放")
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(50, 95)
        self.spin_threshold.setSuffix(" %")
        self.spin_threshold.setValue(85)
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(30, 3600)
        self.spin_interval.setSuffix(" 秒")
        self.spin_interval.setValue(300)
        self.cmb_auto_level = QComboBox()
        self.cmb_auto_level.addItem("温和", "gentle")
        self.cmb_auto_level.addItem("标准", "standard")
        self.cmb_auto_level.addItem("深度", "deep")
        self.cmb_auto_level.setCurrentIndex(1)
        for widget in (self.cmb_auto_level, self.spin_threshold, self.spin_interval):
            widget.setMaximumWidth(190)
        ag.addWidget(self.chk_auto, 0, 0, 1, 4)
        ag.addWidget(QLabel("阈值"), 1, 0)
        ag.addWidget(self.spin_threshold, 1, 1)
        ag.addWidget(QLabel("最小间隔"), 1, 2)
        ag.addWidget(self.spin_interval, 1, 3)
        ag.addWidget(QLabel("力度"), 2, 0)
        ag.addWidget(self.cmb_auto_level, 2, 1)
        self.lbl_auto_state = QLabel("未启用")
        self.lbl_auto_state.setObjectName("Muted")
        ag.addWidget(self.lbl_auto_state, 2, 2, 1, 2)
        lay.addWidget(auto_box)

        proc_box = QGroupBox("内存占用最高的进程")
        pv = QVBoxLayout(proc_box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["进程", "PID", "占用", "路径"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setMinimumHeight(210)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 190)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 80)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 100)
        head.setSectionResizeMode(3, QHeaderView.Stretch)
        pv.addWidget(self.table)
        lay.addWidget(proc_box, 1)

        self.chk_auto.toggled.connect(self._save_auto)
        self.spin_threshold.valueChanged.connect(self._save_auto)
        self.spin_interval.valueChanged.connect(self._save_auto)
        self.cmb_auto_level.currentIndexChanged.connect(self._save_auto)

    def _metric(self, grid: QGridLayout, row: int, title: str) -> QLabel:
        name = QLabel(title)
        name.setObjectName("Muted")
        value = QLabel("—")
        value.setObjectName("Metric")
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(name, row, 0)
        grid.addWidget(value, row, 1)
        grid.setColumnStretch(1, 1)
        return value

    # ---------------- 数据 ----------------
    def refresh(self) -> None:
        st = memory.status()
        perf = memory.performance_info()
        self.ring.set_value(st.percent, st.used, st.total)
        self.lbl_total.setText(core.human_size(st.total))
        self.lbl_used.setText(f"{core.human_size(st.used)}（{st.percent:.0f}%）")
        self.lbl_avail.setText(core.human_size(st.available))
        self.lbl_cached.setText(core.human_size(st.cached))
        self.lbl_commit.setText(
            f"{core.human_size(st.commit_total)} / {core.human_size(st.commit_limit)}")
        self.lbl_procs.setText(
            f"{perf.get('processes', 0)} / {perf.get('threads', 0)}")
        if st.percent >= 85:
            self.lbl_hint.setText("内存紧张，建议立即释放")
        elif st.percent >= 65:
            self.lbl_hint.setText("内存占用偏高")
        else:
            self.lbl_hint.setText("内存状态良好")
        self._refresh_auto_ui()
        self._refresh_table()

    def _refresh_table(self) -> None:
        rows = memory.top_processes(10)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(r["name"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(r["pid"])))
            self.table.setItem(i, 2, QTableWidgetItem(core.human_size(r["rss"])))
            self.table.setItem(i, 3, QTableWidgetItem(r["exe"]))

    def _refresh_auto_ui(self) -> None:
        cfg = memory.auto_config()
        self.chk_auto.blockSignals(True)
        self.spin_threshold.blockSignals(True)
        self.spin_interval.blockSignals(True)
        self.cmb_auto_level.blockSignals(True)
        self.chk_auto.setChecked(cfg["auto_release"])
        self.spin_threshold.setValue(cfg["auto_threshold"])
        self.spin_interval.setValue(cfg["auto_interval"])
        idx = self.cmb_auto_level.findData(cfg["auto_level"])
        self.cmb_auto_level.setCurrentIndex(idx if idx >= 0 else 1)
        self.chk_auto.blockSignals(False)
        self.spin_threshold.blockSignals(False)
        self.spin_interval.blockSignals(False)
        self.cmb_auto_level.blockSignals(False)
        if cfg["auto_release"]:
            self.lbl_auto_state.setText(
                f"已启用：超过 {cfg['auto_threshold']}% 且间隔 ≥"
                f"{cfg['auto_interval']}s；已运行 {self._autoreleaser.runs} 次")
        else:
            self.lbl_auto_state.setText("未启用")

    def _save_auto(self) -> None:
        core.update_config(
            auto_release=self.chk_auto.isChecked(),
            auto_threshold=self.spin_threshold.value(),
            auto_interval=self.spin_interval.value(),
            auto_level=self.cmb_auto_level.currentData(),
        )
        self._refresh_auto_ui()

    def _tick(self) -> None:
        if self.chk_auto.isChecked():
            self._autoreleaser.maybe_release()
        # 仅在当前页可见时刷新，避免无谓开销
        if self.isVisible():
            self.refresh()

    # ---------------- 释放 ----------------
    def release_now(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        level = self.cmb_level.currentData()
        self.btn_release.setEnabled(False)
        self.btn_release.setText("正在释放…")
        self.lbl_result.setText("准备中…")
        self._worker = ReleaseWorker(level)
        self._worker.step.connect(lambda n: self.lbl_result.setText(f"正在：{n}"))
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, data: dict[str, Any]) -> None:
        self.btn_release.setEnabled(True)
        self.btn_release.setText("一键释放内存")
        freed = int(data.get("freed", 0))
        before = data.get("before", {})
        after = data.get("after", {})
        text = (f"释放 {core.human_size(freed)}　"
                f"占用 {before.get('percent', 0):.0f}% → "
                f"{after.get('percent', 0):.0f}%　"
                f"修剪 {data.get('trimmed', 0)} 个进程")
        self.lbl_result.setText(text)
        self.set_status(f"内存释放完成：{text}")
        if self.notify:
            self.notify("内存释放完成", text)
        self.refresh()

    def shutdown(self) -> None:
        self._timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.wait(3000)
