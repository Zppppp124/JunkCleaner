"""可信软件页面：白名单管理、已安装软件选择、Windows Defender 排除项。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from . import core, trust
from . import archive

GOOD = "#2ec4a5"
WARN = "#ff9f43"
DANGER = "#f4577c"
MUTED = "#8d86a8"
TEXT = "#3a3352"
ACCENT = "#8b6cf6"
BORDER = "#e4ddf7"
PANEL2 = "#faf8ff"
SOFT = "#efe9ff"


class InstalledScanWorker(QThread):
    done = Signal(list)

    def run(self) -> None:
        try:
            self.done.emit(trust.installed_software())
        except Exception:  # noqa: BLE001
            self.done.emit([])


class DefenderQueryWorker(QThread):
    done = Signal(list)

    def run(self) -> None:
        try:
            self.done.emit(trust.defender_exclusions())
        except Exception:  # noqa: BLE001
            self.done.emit([])


class ArchiveListWorker(QThread):
    """后台读取压缩包目录，避免大包卡住界面。"""

    done = Signal(str, list)
    failed = Signal(str, str)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            entries = archive.list_entries(self.path)
            self.done.emit(self.path, entries)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.path, str(exc))


class ArchivePickerDialog(QDialog):
    """从压缩包中选择要加入白名单的单个文件。"""

    def __init__(self, path: str, entries: list[archive.ArchiveEntry],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"压缩包内容 · {Path(path).name}")
        self.resize(680, 480)
        self.path = path
        self.entries = entries
        self.selected: archive.ArchiveEntry | None = None
        self.hash_ready = False

        lay = QVBoxLayout(self)
        tip = QLabel(
            "选择包内的文件加入白名单。加入后会用它的内容指纹（SHA-256）匹配，"
            "该文件无论被解压/复制到哪个目录，运行时都不会被拦截。")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("按文件名筛选…")
        self.search.textChanged.connect(self._refilter)
        self.chk_exe = QCheckBox("只看可执行文件")
        self.chk_exe.setChecked(True)
        self.chk_exe.toggled.connect(self._refilter)
        row.addWidget(self.search, 1)
        row.addWidget(self.chk_exe)
        lay.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["选择", "文件", "大小"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 60)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 110)
        self.table.itemDoubleClicked.connect(lambda _i: self._accept())
        lay.addWidget(self.table, 1)

        self.lbl_state = QLabel(f"共 {len(entries)} 项")
        self.lbl_state.setObjectName("Muted")
        lay.addWidget(self.lbl_state)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("加入白名单")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refilter()

    def _refilter(self) -> None:
        rows = archive.filter_entries(
            self.entries, keyword=self.search.text().strip(),
            executables_only=self.chk_exe.isChecked())
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, e in enumerate(rows):
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)
            self.table.setItem(i, 0, item)
            self.table.setItem(i, 1, QTableWidgetItem(e.name))
            self.table.setItem(i, 2, QTableWidgetItem(
                core.human_size(e.size) if e.size else "—"))
        self.lbl_state.setText(f"显示 {len(rows)} / 共 {len(self.entries)} 项")

    def _checked_entry(self) -> archive.ArchiveEntry | None:
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                return self.rows[i]
        # 没有勾选就用当前选中行
        sel = self.table.selectionModel().selectedRows()
        if sel:
            return self.rows[sel[0].row()]
        return None

    def _accept(self) -> None:
        entry = self._checked_entry()
        if entry is None:
            QMessageBox.information(self, "未选择", "请勾选或点选一个文件。")
            return
        self.selected = entry
        self.accept()


def check_item(text: str, checked: bool) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    return item


class TrustPage(QWidget):
    """可信软件管理页。"""

    def __init__(self, notify: Callable[[str, str], None] | None = None,
                 status: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self.notify = notify
        self.set_status = status or (lambda _m: None)
        self.installed: list[dict[str, Any]] = []
        self._worker: QThread | None = None
        self._def_worker: QThread | None = None
        self._closing = False
        self._build()
        self.refresh()
        QThread.msleep(0)

    # ---------------- 界面 ----------------
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        intro = QLabel(
            "把信任的软件加入白名单后，扫描与实时防护都会跳过它，避免误杀；"
            "必要时可同时加入 Windows Defender 排除项。")
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_installed(), "从已安装软件选择")
        self.tabs.addTab(self._tab_rules(), "白名单规则")
        self.tabs.addTab(self._tab_defender(), "Defender 排除项")
        lay.addWidget(self.tabs, 1)

    # ---------------- 子页 1：已安装 ----------------
    def _tab_installed(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self.sw_search = QLineEdit()
        self.sw_search.setPlaceholderText("搜索软件名 / 发行商…")
        self.sw_search.textChanged.connect(self._filter_installed)
        btn_reload = QPushButton("重新读取")
        btn_reload.setObjectName("Ghost")
        btn_reload.clicked.connect(self.reload_installed)
        self.lbl_count = QLabel("")
        self.lbl_count.setObjectName("Muted")
        bar.addWidget(self.sw_search, 1)
        bar.addWidget(btn_reload)
        bar.addWidget(self.lbl_count)
        lay.addLayout(bar)

        self.sw_table = QTableWidget(0, 4)
        self.sw_table.setHorizontalHeaderLabels(["", "软件", "发行商", "信任状态"])
        self.sw_table.verticalHeader().setVisible(False)
        self.sw_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.sw_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sw_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        head = self.sw_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        self.sw_table.setColumnWidth(0, 34)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        head.setSectionResizeMode(2, QHeaderView.Fixed)
        self.sw_table.setColumnWidth(2, 230)
        head.setSectionResizeMode(3, QHeaderView.Fixed)
        self.sw_table.setColumnWidth(3, 110)
        self.sw_table.itemChanged.connect(self._on_sw_check)
        lay.addWidget(self.sw_table, 1)

        actions = QHBoxLayout()
        self.btn_trust_sel = QPushButton("信任选中软件")
        self.btn_trust_sel.setObjectName("Primary")
        self.btn_trust_sel.clicked.connect(self.trust_selected)
        self.chk_defender = QCheckBox("同时加入 Defender 排除项")
        self.chk_defender.setChecked(True)
        self.btn_sel_all = QPushButton("全选")
        self.btn_sel_all.setObjectName("Ghost")
        self.btn_sel_all.clicked.connect(lambda: self._check_all(True))
        self.btn_sel_none = QPushButton("全不选")
        self.btn_sel_none.setObjectName("Ghost")
        self.btn_sel_none.clicked.connect(lambda: self._check_all(False))
        actions.addWidget(self.btn_trust_sel)
        actions.addWidget(self.chk_defender)
        actions.addStretch(1)
        actions.addWidget(self.btn_sel_all)
        actions.addWidget(self.btn_sel_none)
        lay.addLayout(actions)
        return page

    # ---------------- 子页 2：规则 ----------------
    def _tab_rules(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        box = QGroupBox("手动添加白名单规则")
        grid = QGridLayout(box)
        self.rule_kind = QComboBox()
        for key, label in trust.TRUST_KINDS.items():
            self.rule_kind.addItem(label, key)
        self.rule_value = QLineEdit()
        self.rule_value.setPlaceholderText("选择文件 / 目录，或直接填写内容")
        self.rule_name = QLineEdit()
        self.rule_name.setPlaceholderText("备注名称（可选）")
        btn_browse_file = QPushButton("选择文件")
        btn_browse_file.setObjectName("Ghost")
        btn_browse_file.clicked.connect(self._browse_file)
        btn_browse_dir = QPushButton("选择目录")
        btn_browse_dir.setObjectName("Ghost")
        btn_browse_dir.clicked.connect(self._browse_dir)
        btn_browse_arc = QPushButton("选择压缩包内文件")
        btn_browse_arc.setObjectName("Ghost")
        btn_browse_arc.setToolTip(
            "从 zip / 7z / rar / tar 中选择单个文件，按内容指纹加入白名单；"
            "解压到任何位置后都不会被拦截")
        btn_browse_arc.clicked.connect(self._browse_archive)
        btn_add = QPushButton("添加白名单")
        btn_add.setObjectName("Primary")
        btn_add.clicked.connect(self.add_rule)
        grid.addWidget(QLabel("类型"), 0, 0)
        grid.addWidget(self.rule_kind, 0, 1, 1, 3)
        grid.addWidget(QLabel("内容"), 1, 0)
        grid.addWidget(self.rule_value, 1, 1)
        grid.addWidget(btn_browse_file, 1, 2)
        grid.addWidget(btn_browse_dir, 1, 3)
        grid.addWidget(QLabel("名称"), 2, 0)
        grid.addWidget(self.rule_name, 2, 1, 1, 2)
        grid.addWidget(btn_add, 2, 3)
        grid.addWidget(btn_browse_arc, 3, 1, 1, 3)
        lay.addWidget(box)

        self.rule_table = QTableWidget(0, 5)
        self.rule_table.setHorizontalHeaderLabels(["启用", "名称", "类型", "内容", "添加时间"])
        self.rule_table.verticalHeader().setVisible(False)
        self.rule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        rh = self.rule_table.horizontalHeader()
        for i, w in enumerate([60, 190, 120]):
            rh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.rule_table.setColumnWidth(i, w)
        rh.setSectionResizeMode(3, QHeaderView.Stretch)
        rh.setSectionResizeMode(4, QHeaderView.Fixed)
        self.rule_table.setColumnWidth(4, 150)
        self.rule_table.itemChanged.connect(self._on_rule_toggle)
        lay.addWidget(self.rule_table, 1)

        row = QHBoxLayout()
        btn_del = QPushButton("移除选中规则")
        btn_del.setObjectName("Danger")
        btn_del.clicked.connect(self.remove_rules)
        row.addWidget(btn_del)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    # ---------------- 子页 3：Defender ----------------
    def _tab_defender(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        warn = QLabel("⚠ 加入 Defender 排除项会让该路径不再被 Windows 实时保护扫描，"
                      "会降低系统安全性。请只对确实信任的软件使用。")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color:{WARN}")
        lay.addWidget(warn)

        row = QHBoxLayout()
        self.def_input = QLineEdit()
        self.def_input.setPlaceholderText("要排除的文件或目录")
        btn_pick = QPushButton("选择目录")
        btn_pick.setObjectName("Ghost")
        btn_pick.clicked.connect(self._browse_def_dir)
        btn_add = QPushButton("添加排除项")
        btn_add.clicked.connect(self.add_defender)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("Ghost")
        btn_refresh.clicked.connect(self.refresh_defender)
        row.addWidget(self.def_input, 1)
        row.addWidget(btn_pick)
        row.addWidget(btn_add)
        row.addWidget(btn_refresh)
        lay.addLayout(row)

        self.def_table = QTableWidget(0, 2)
        self.def_table.setHorizontalHeaderLabels(["排除路径", ""])
        self.def_table.verticalHeader().setVisible(False)
        self.def_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.def_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        dh = self.def_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.Fixed)
        self.def_table.setColumnWidth(1, 90)
        lay.addWidget(self.def_table, 1)
        return page

    # ---------------- 已安装软件 ----------------
    def refresh(self) -> None:
        self._refresh_rules()
        self.reload_installed()
        self.refresh_defender()

    def reload_installed(self) -> None:
        if self._closing:
            return
        if self._worker and self._worker.isRunning():
            return
        self.lbl_count.setText("读取中…")
        self._worker = InstalledScanWorker()
        self._worker.done.connect(self._on_installed)
        self._worker.start()

    def _on_installed(self, rows: list[dict[str, Any]]) -> None:
        self.installed = rows
        self.lbl_count.setText(f"共 {len(rows)} 个软件")
        self._render_installed()

    def _render_installed(self) -> None:
        text = self.sw_search.text().strip().lower()
        rows = [r for r in self.installed
                if not text or text in (r["name"] + r["publisher"]).lower()]
        self.sw_table.blockSignals(True)
        self.sw_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            chk = check_item("", False)
            chk.setData(Qt.UserRole, r)
            self.sw_table.setItem(i, 0, chk)
            self.sw_table.setItem(i, 1, QTableWidgetItem(r["name"]))
            self.sw_table.setItem(i, 2, QTableWidgetItem(r["publisher"]))
            state = QTableWidgetItem("已信任" if r["trusted"] else "未信任")
            state.setForeground(Qt.green if r["trusted"] else Qt.gray)  # type: ignore[arg-type]
            self.sw_table.setItem(i, 3, state)
        self.sw_table.blockSignals(False)

    def _filter_installed(self) -> None:
        self._render_installed()

    def _check_all(self, value: bool) -> None:
        self.sw_table.blockSignals(True)
        for i in range(self.sw_table.rowCount()):
            item = self.sw_table.item(i, 0)
            if item:
                item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        self.sw_table.blockSignals(False)

    def _on_sw_check(self, _item: QTableWidgetItem) -> None:
        pass

    def trust_selected(self) -> None:
        picked: list[dict[str, Any]] = []
        for i in range(self.sw_table.rowCount()):
            item = self.sw_table.item(i, 0)
            if item and item.checkState() == Qt.Checked:
                data = item.data(Qt.UserRole)
                if data:
                    picked.append(data)
        if not picked:
            QMessageBox.information(self, "未选择", "请先勾选要信任的软件。")
            return
        with_defender = self.chk_defender.isChecked()
        results: list[str] = []
        defender_fail: list[str] = []
        for app in picked:
            target = app.get("location") or app.get("exe") or ""
            if not target:
                results.append(f"{app['name']}：未找到安装路径，已按名称信任")
                trust.add_trust(app["name"], "name", app["name"], source="installed")
                continue
            trust.add_trust(app["name"], "path", target, source="installed")
            results.append(f"{app['name']}：已信任 {target}")
            if with_defender:
                ok, detail = trust.add_defender_exclusion(target)
                if not ok:
                    defender_fail.append(f"{app['name']}（{detail}）")
        self._refresh_rules()
        self.reload_installed()
        self.refresh_defender()
        msg = f"已信任 {len(picked)} 个软件。"
        if defender_fail:
            msg += "\n\n以下软件未能加入 Defender 排除项：\n" + "\n".join(defender_fail)
        if self.notify:
            self.notify("可信软件已添加", msg.splitlines()[0])
        self.set_status(msg.splitlines()[0])
        QMessageBox.information(self, "完成", msg)

    # ---------------- 规则 ----------------
    def _refresh_rules(self) -> None:
        entries = trust.load_trust()
        self.rule_table.blockSignals(True)
        self.rule_table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            chk = check_item("", bool(e.get("enabled", True)))
            chk.setData(Qt.UserRole, e.get("id"))
            self.rule_table.setItem(i, 0, chk)
            self.rule_table.setItem(i, 1, QTableWidgetItem(e.get("name", "")))
            kind = QTableWidgetItem(trust.TRUST_KINDS.get(e.get("kind", ""), e.get("kind", "")))
            self.rule_table.setItem(i, 2, kind)
            self.rule_table.setItem(i, 3, QTableWidgetItem(e.get("value", "")))
            self.rule_table.setItem(i, 4, QTableWidgetItem(e.get("added", "")))
        self.rule_table.blockSignals(False)

    def _on_rule_toggle(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        entry_id = item.data(Qt.UserRole)
        if entry_id:
            trust.set_enabled(entry_id, item.checkState() == Qt.Checked)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择可信程序", "",
                                              "程序 (*.exe *.dll);;所有文件 (*.*)")
        if path:
            self.rule_value.setText(path)
            if not self.rule_name.text():
                self.rule_name.setText(Path(path).stem)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择可信目录")
        if path:
            self.rule_value.setText(path)
            if not self.rule_name.text():
                self.rule_name.setText(Path(path).name)

    def _browse_archive(self) -> None:
        """从压缩包中选择单个文件，按内容指纹加入白名单。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择压缩包", "",
            "压缩包 (*.zip *.7z *.rar *.tar *.gz *.tgz *.bz2 *.xz *.jar);;所有文件 (*.*)")
        if not path:
            return
        entries = archive.list_entries(path)
        if not entries:
            QMessageBox.warning(
                self, "无法读取",
                "无法读取该压缩包。rar 需要安装 WinRAR（含 UnRAR.exe），"
                "7z 需要 py7zr 模块。")
            return
        dialog = ArchivePickerDialog(path, entries, self)
        if dialog.exec() != QDialog.Accepted or dialog.selected is None:
            return
        entry = dialog.selected
        # 在后台计算包内成员指纹
        self.set_status(f"正在计算 {entry.name} 的内容指纹…")
        digest = archive.read_member_hash(path, entry.name)
        if not digest:
            QMessageBox.warning(self, "失败", f"无法读取包内文件：{entry.name}")
            return
        name = f"{Path(path).stem} / {Path(entry.name).name}"
        trust.add_trust(name, "hash", digest, source="archive",
                        note=f"{path} :: {entry.name}")
        self._refresh_rules()
        self.reload_installed()
        self.set_status(f"已按内容指纹加入白名单：{entry.name}")
        QMessageBox.information(
            self, "已加入白名单",
            f"{entry.name}\n\n指纹：{digest[:16]}…\n\n"
            "该文件被解压或复制到任何目录后运行都不会被拦截。")

    def add_rule(self) -> None:
        kind = self.rule_kind.currentData()
        value = self.rule_value.text().strip()
        name = self.rule_name.text().strip()
        if not value:
            QMessageBox.information(self, "缺少内容", "请填写或选择要信任的内容。")
            return
        if kind == "path" and not Path(value).exists():
            if QMessageBox.question(self, "路径不存在",
                                    "该路径当前不存在，仍要添加吗？") != QMessageBox.Yes:
                return
        if kind == "hash":
            value = value.lower()
        trust.add_trust(name or value, kind, value, source="manual")
        self.rule_value.clear()
        self.rule_name.clear()
        self._refresh_rules()
        self.reload_installed()
        self.set_status(f"已添加白名单：{name or value}")

    def remove_rules(self) -> None:
        rows = self.rule_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未选择", "请先选择要移除的规则。")
            return
        for idx in rows:
            item = self.rule_table.item(idx.row(), 0)
            if item and item.data(Qt.UserRole):
                trust.remove_trust(item.data(Qt.UserRole))
        self._refresh_rules()
        self.reload_installed()
        self.set_status("已移除选中白名单规则")

    # ---------------- Defender ----------------
    def refresh_defender(self) -> None:
        if self._closing:
            return
        if self._def_worker and self._def_worker.isRunning():
            return
        worker = DefenderQueryWorker()
        worker.done.connect(self._on_defender)
        worker.start()
        self._def_worker = worker

    def shutdown(self) -> None:
        """退出前收尾，避免 QThread 在运行中被析构导致崩溃。"""
        self._closing = True
        for worker in (self._worker, self._def_worker):
            try:
                if worker and worker.isRunning():
                    worker.quit()
                    worker.wait(4000)
            except Exception:  # noqa: BLE001
                pass

    def _on_defender(self, paths: list[str]) -> None:
        self.def_table.setRowCount(len(paths))
        for i, p in enumerate(paths):
            self.def_table.setItem(i, 0, QTableWidgetItem(p))
            btn = QPushButton("移除")
            btn.setObjectName("Ghost")
            btn.clicked.connect(lambda _c=False, path=p: self._remove_defender(path))
            self.def_table.setCellWidget(i, 1, btn)

    def _browse_def_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目录")
        if path:
            self.def_input.setText(path)

    def add_defender(self) -> None:
        path = self.def_input.text().strip()
        if not path:
            return
        if QMessageBox.question(
                self, "确认",
                f"将 {path} 加入 Windows Defender 排除项？\n\n"
                "这会让该路径不再被系统实时保护扫描，确认该软件确实可信。"
        ) != QMessageBox.Yes:
            return
        ok, detail = trust.add_defender_exclusion(path)
        if ok:
            self.def_input.clear()
            self.refresh_defender()
            self.set_status(f"已加入 Defender 排除项：{path}")
        else:
            QMessageBox.warning(self, "失败", f"添加失败：{detail}")

    def _remove_defender(self, path: str) -> None:
        if QMessageBox.question(self, "确认", f"移除排除项 {path}？") != QMessageBox.Yes:
            return
        ok, detail = trust.remove_defender_exclusion(path)
        if ok:
            self.refresh_defender()
        else:
            QMessageBox.warning(self, "失败", f"移除失败：{detail}")
