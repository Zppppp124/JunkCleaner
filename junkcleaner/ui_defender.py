"""Windows Defender 策略优化页面（淡紫可爱风）。"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import core, defender

GOOD = "#2ec4a5"
WARN = "#ff9f43"
DANGER = "#f4577c"
MUTED = "#8d86a8"
TEXT = "#3a3352"
ACCENT = "#8b6cf6"
SOFT = "#efe9ff"


class ApplyWorker(QThread):
    done = Signal(dict)

    def __init__(self, preset: str) -> None:
        super().__init__()
        self.preset = preset

    def run(self) -> None:
        self.done.emit(defender.apply_preset(self.preset))


class StatusWorker(QThread):
    done = Signal(dict)

    def run(self) -> None:
        try:
            self.done.emit({"live": defender.live_status(),
                            "current": defender.read_current(),
                            "backups": defender.list_backups()})
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"error": str(exc)})


class DefenderPage(QWidget):
    """把 Defender「扫描」策略的性能损耗压到最低。"""

    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.notify = notify
        self.set_status = status or (lambda _m: None)
        self._applying = False
        self._worker: QThread | None = None
        self._build()
        self.refresh()

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(11)

        tip = QLabel(
            "调整「计算机配置 > 管理模板 > Windows 组件 > Microsoft Defender 防病毒 > "
            "扫描」这一页的策略：**保留扫描能力**，只把 CPU、磁盘、后台占用压到最低。"
            "所有改动都会先完整备份，可一键还原；不涉及实时保护开关。")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)

        self.banner = QFrame()
        self.banner.setObjectName("Card")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        bl.addWidget(self.banner_label, 1)
        lay.addWidget(self.banner)

        ctrl = QGroupBox("策略预设")
        cg = QHBoxLayout(ctrl)
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItem("平衡（推荐）· 几乎无安全损失", "balanced")
        self.cmb_preset.addItem("激进 · 最低开销（有安全代价）", "aggressive")
        self.cmb_preset.addItem("全部关闭 · 关闭所有可关的扫描", "off")
        self.btn_apply = QPushButton("应用到系统")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self.apply_now)
        self.btn_restore = QPushButton("还原上次备份")
        self.btn_restore.setObjectName("Ghost")
        self.btn_restore.clicked.connect(self.restore_last)
        self.btn_defaults = QPushButton("全部恢复未配置")
        self.btn_defaults.setObjectName("Ghost")
        self.btn_defaults.clicked.connect(self.restore_defaults)
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("Ghost")
        self.btn_refresh.clicked.connect(self.refresh)
        self.chk_autostart = QCheckBox("每次启动本程序时自动应用")
        self.chk_autostart.toggled.connect(
            lambda v: core.update_config(defender_auto_apply=v))
        cg.addWidget(QLabel("预设"))
        cg.addWidget(self.cmb_preset, 1)
        cg.addWidget(self.chk_autostart)
        cg.addWidget(self.btn_apply)
        cg.addWidget(self.btn_restore)
        cg.addWidget(self.btn_defaults)
        cg.addWidget(self.btn_refresh)
        lay.addWidget(ctrl)

        body = QHBoxLayout()
        body.setSpacing(11)

        left = QGroupBox("扫描策略项")
        lv = QVBoxLayout(left)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["设置", "当前", "将改为", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 210)
        head.setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 70)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 70)
        head.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 320)
        lv.addWidget(self.table)
        body.addWidget(left, 3)

        right = QVBoxLayout()
        self.status_box = QGroupBox("Defender 实际状态")
        sv = QVBoxLayout(self.status_box)
        self.lbl_live = QLabel("读取中…")
        self.lbl_live.setWordWrap(True)
        self.lbl_live.setTextFormat(Qt.RichText)
        sv.addWidget(self.lbl_live)
        right.addWidget(self.status_box)

        backup_box = QGroupBox("备份记录")
        bv = QVBoxLayout(backup_box)
        self.backup_list = QTableWidget(0, 2)
        self.backup_list.setHorizontalHeaderLabels(["时间", "项数"])
        self.backup_list.verticalHeader().setVisible(False)
        self.backup_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.backup_list.setSelectionBehavior(QAbstractItemView.SelectRows)
        bh = self.backup_list.horizontalHeader()
        bh.setSectionResizeMode(0, QHeaderView.Stretch)
        bh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.backup_list.setColumnWidth(1, 60)
        self.backup_list.setMinimumHeight(150)
        bv.addWidget(self.backup_list)
        self.btn_restore_sel = QPushButton("还原选中备份")
        self.btn_restore_sel.setObjectName("Ghost")
        self.btn_restore_sel.clicked.connect(self.restore_selected)
        bv.addWidget(self.btn_restore_sel)
        right.addWidget(backup_box)
        right.addStretch(1)
        body.addLayout(right, 2)
        lay.addLayout(body, 1)

    # ---------------- 数据 ----------------
    def refresh(self) -> None:
        self._render_preview()
        self.chk_autostart.blockSignals(True)
        self.chk_autostart.setChecked(
            bool(core.load_config().get("defender_auto_apply", False)))
        self.chk_autostart.blockSignals(False)
        if self._worker and self._worker.isRunning():
            return
        self._worker = StatusWorker()
        self._worker.done.connect(self._on_status)
        self._worker.start()

    def shutdown(self) -> None:
        """关闭窗口前等待后台线程结束。

        构造时就启动了 StatusWorker 查询状态；若进程退出时线程仍在跑，
        Qt 会在线程存活的情况下析构对象，导致进程以 0xc0000409 异常退出。
        """
        w = getattr(self, "_worker", None)
        if w is None:
            return
        try:
            if w.isRunning():
                w.quit()
                if not w.wait(3000):
                    w.terminate()
                    w.wait(1000)
        except Exception:  # noqa: BLE001
            pass

    def _render_preview(self) -> None:
        preset = self.cmb_preset.currentData()
        rows = defender.preview(preset)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            name = QTableWidgetItem(r["name"])
            if r["risk"] == "high":
                name.setForeground(Qt.red)
            self.table.setItem(i, 0, name)
            cur = "未配置" if r["current"] is None else str(r["current"])
            item_cur = QTableWidgetItem(cur)
            if r["changed"]:
                item_cur.setForeground(Qt.gray if False else Qt.darkYellow)
            self.table.setItem(i, 1, item_cur)
            tgt = QTableWidgetItem(str(r["target"]))
            tgt.setForeground(Qt.darkGreen)
            self.table.setItem(i, 2, tgt)
            desc = QTableWidgetItem(r["desc"])
            desc.setToolTip(r["desc"])
            if r["risk"] == "high":
                desc.setForeground(Qt.red)
            self.table.setItem(i, 3, desc)
            self.table.setRowHeight(i, 30)

    def _on_status(self, data: dict[str, Any]) -> None:
        if "error" in data:
            self.lbl_live.setText(f"读取失败：{data['error']}")
            return
        live = data.get("live") or {}
        st = live.get("status") or {}
        pref = live.get("pref") or {}
        tamper = st.get("IsTamperProtected")
        rt = st.get("RealTimeProtectionEnabled")
        lines = [
            f"<b>防病毒服务</b>：{'已启用' if st.get('AntivirusEnabled') else '未启用'}",
            f"<b>实时保护</b>：{'开启' if rt else '关闭'}"
            f"　<span style='color:{MUTED}'>（本工具不修改此项）</span>",
            f"<b>篡改防护</b>：{'开启（将阻止写入）' if tamper else '关闭'}",
            f"<b>扫描 CPU 上限</b>：{pref.get('ScanAvgCPULoadFactor', '—')}%",
            f"<b>运行模式</b>：{st.get('AMRunningMode', '—')}",
        ]
        self.lbl_live.setText("<br>".join(lines))
        if tamper:
            self._show_banner(
                "篡改防护已开启，策略写入可能被系统拒绝。请先在「Windows 安全中心 > "
                "病毒和威胁防护 > 管理设置」中关闭篡改防护后重试。", DANGER)
        elif not core.is_admin():
            self._show_banner("当前不是管理员，无法修改组策略。", WARN)
        else:
            self._show_banner("管理员权限就绪，篡改防护未阻止写入。", GOOD)
        backups = data.get("backups") or []
        self.backup_list.setRowCount(len(backups))
        for i, b in enumerate(backups):
            self.backup_list.setItem(i, 0, QTableWidgetItem(b.get("time", "")))
            self.backup_list.setItem(i, 1, QTableWidgetItem(str(b.get("count", 0))))
            self.backup_list.item(i, 0).setData(Qt.UserRole, b.get("_file", ""))

    def _show_banner(self, text: str, color: str) -> None:
        self.banner_label.setText(text)
        self.banner_label.setStyleSheet(f"color:{color};font-weight:600;")

    # ---------------- 操作 ----------------
    def apply_now(self) -> None:
        if self._applying:
            return
        if not core.is_admin():
            QMessageBox.warning(self, "需要管理员权限",
                                "修改组策略需要管理员权限，请以管理员身份重启。")
            return
        preset = self.cmb_preset.currentData()
        label = defender.PRESET_LABEL.get(preset, preset)
        rows = defender.preview(preset)
        changed = [r for r in rows if r["changed"]]
        high = [r for r in rows if r["risk"] == "high"]
        msg = (f"将应用「{label}」，共 {len(rows)} 项（其中 {len(changed)} 项会变化）。\n\n"
               "· 不修改实时保护开关\n"
               "· 修改前会自动完整备份，可一键还原\n")
        if preset == "off":
            msg += ("\n⚠ 该预设会关闭压缩包扫描、加壳扫描、启发式分析等，"
                    "并跳过网络文件 / 可移动设备 / 邮件，\n"
                    "只保留最基本的实时监控。\n"
                    "这会**明显降低病毒检出率**，请自行权衡。\n")
        if high:
            msg += "\n注意：以下项目有安全代价：\n" + "\n".join(
                f"　· {h['name']}" for h in high)
        if QMessageBox.question(self, "确认应用", msg) != QMessageBox.Yes:
            return
        self._applying = True
        self.btn_apply.setEnabled(False)
        self.btn_apply.setText("应用……")
        worker = ApplyWorker(preset)
        worker.done.connect(self._on_applied)
        worker.start()
        self._apply_worker = worker

    def _on_applied(self, result: dict[str, Any]) -> None:
        self._applying = False
        self.btn_apply.setEnabled(True)
        self.btn_apply.setText("应用到系统")
        if result.get("ok"):
            text = (f"已应用 {result.get('applied', 0)} 项策略。\n"
                    f"备份：{result.get('backup', '')}")
            self.set_status(text.splitlines()[0])
            if self.notify:
                self.notify("Defender 策略已优化", text.splitlines()[0])
        else:
            text = "部分失败：\n" + "\n".join(result.get("failed") or [])
        QMessageBox.information(self, "完成", text)
        self.refresh()

    def restore_last(self) -> None:
        backups = defender.list_backups()
        if not backups:
            QMessageBox.information(self, "无备份", "还没有任何备份记录。")
            return
        self._restore_path(backups[0]["_file"], backups[0].get("time", ""))

    def restore_selected(self) -> None:
        rows = self.backup_list.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未选择", "请先选择一条备份。")
            return
        item = self.backup_list.item(rows[0].row(), 0)
        self._restore_path(item.data(Qt.UserRole), item.text())

    def _restore_path(self, path: str, when: str) -> None:
        if not path:
            return
        if QMessageBox.question(self, "确认还原",
                                f"还原 {when} 的 Defender 策略备份？") != QMessageBox.Yes:
            return
        result = defender.restore_backup(path)
        if result.get("ok"):
            QMessageBox.information(
                self, "已还原",
                f"恢复 {result.get('restored', 0)} 项，移除 {result.get('removed', 0)} 项。")
        else:
            QMessageBox.warning(self, "失败", str(result.get("error", "")))
        self.refresh()

    def restore_defaults(self) -> None:
        if QMessageBox.question(
                self, "确认",
                "把本工具写入的全部扫描策略删除，恢复为「未配置」？") != QMessageBox.Yes:
            return
        result = defender.restore_defaults()
        if result.get("ok"):
            QMessageBox.information(self, "完成",
                                    f"已删除 {result.get('removed', 0)} 项策略值。")
        else:
            QMessageBox.warning(self, "失败", str(result.get("error", "")))
        self.refresh()

    def auto_apply_on_start(self) -> None:
        """启动时调用：按配置自动应用。"""
        if not core.is_admin():
            return
        cfg = core.load_config()
        if not cfg.get("defender_auto_apply"):
            return
        preset = cfg.get("defender_preset", "balanced")
        result = defender.apply_preset(preset)
        if self.notify:
            self.notify("Defender 策略已自动优化",
                        f"{defender.PRESET_LABEL.get(preset, preset)}："
                        f"应用 {result.get('applied', 0)} 项")
