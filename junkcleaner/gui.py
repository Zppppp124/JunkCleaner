"""JunkCleaner 净扫 —— GUI 主界面（PySide6）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QPainter,
                           QPainterPath, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QStyle,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import APP_NAME, __version__, cleaner, core, guard, scanner, trust
from .ui_trust import TrustPage
from .ui_memory import MemoryPage
from .ui_defender import DefenderPage
from .ui_tuning import TuningPage
from .ui_hardware import HardwarePage

# ---------------------------------------------------------------- 配色（淡紫可爱风）
BG = "#f4f1fb"            # 主背景：淡紫
PANEL = "#ffffff"         # 卡片：白
PANEL2 = "#faf8ff"        # 输入/表格：极淡紫
SOFT = "#efe9ff"          # 柔和紫
SOFT2 = "#f6f2ff"
BORDER = "#e4ddf7"
TEXT = "#3a3352"          # 墨紫
MUTED = "#8d86a8"
ACCENT = "#8b6cf6"        # 主紫
ACCENT_DARK = "#6d4ee6"
ROGUE = "#f4577c"         # 可爱粉红
BUNDLE = "#ffab3d"        # 可爱橙
DISPUTED = "#9d97b5"
GOOD = "#2ec4a5"          # 薄荷绿
NORMAL = "#5aa9f0"        # 天蓝

RISK_COLOR = {"rogue": ROGUE, "bundle": BUNDLE, "disputed": DISPUTED,
              "normal": NORMAL}
RISK_TEXT = {"rogue": "流氓", "bundle": "捆绑", "disputed": "争议", "normal": "正常软件"}

QSS = f"""
QMainWindow, QWidget {{ background:{BG}; color:{TEXT};
  font-family:"Microsoft YaHei UI","Segoe UI","黑体",sans-serif; font-size:13px; }}
QFrame#Card, QGroupBox {{ background:{PANEL}; border:1px solid {BORDER};
  border-radius:14px; }}
QFrame#Hero {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
  stop:0 #efe6ff, stop:0.5 #f7f1ff, stop:1 #eaf3ff);
  border:1px solid #ddd0ff; border-radius:18px; }}
QLabel, QCheckBox, QRadioButton {{ background:transparent; }}
QGroupBox {{ margin-top:16px; padding:16px 14px 14px 14px; font-weight:700;
  color:{TEXT}; }}
QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 7px;
  color:{ACCENT_DARK}; font-weight:700; }}
QLabel#H1 {{ font-size:23px; font-weight:800; color:{TEXT}; }}
QLabel#H2 {{ font-size:15px; font-weight:700; }}
QLabel#Tag {{ color:{ACCENT}; font-size:12px; }}
QLabel#Muted {{ color:{MUTED}; }}
QLabel#Stat {{ font-size:21px; font-weight:800; color:{ACCENT}; }}
QLabel#Metric {{ font-size:14px; font-weight:700; color:{TEXT}; }}
QPushButton {{ background:{SOFT}; border:1px solid #dcd2fb; border-radius:11px;
  padding:8px 16px; color:{TEXT}; font-weight:600; }}
QPushButton:hover {{ background:#e6dcff; border-color:{ACCENT}; }}
QPushButton:pressed {{ background:#dbd0ff; }}
QPushButton:disabled {{ color:#b6b0c8; background:#f0edf7; border-color:#e7e2f2; }}
QPushButton#Primary {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
  stop:0 {ACCENT}, stop:1 #a07bff); border:1px solid #b7a1ff; color:#ffffff;
  font-weight:800; }}
QPushButton#Primary:hover {{ background:{ACCENT_DARK}; }}
QPushButton#Danger {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
  stop:0 {ROGUE}, stop:1 #ff8aa3); border:1px solid #ff9db4; color:#ffffff;
  font-weight:800; }}
QPushButton#Danger:hover {{ background:#e94a70; }}
QPushButton#Ghost {{ background:#ffffff; border:1px solid {BORDER}; }}
QPushButton#Ghost:hover {{ border-color:{ACCENT}; color:{ACCENT_DARK}; }}
QLineEdit, QComboBox, QSpinBox {{ background:{PANEL2}; border:1px solid {BORDER};
  border-radius:10px; padding:7px 10px; selection-background-color:{SOFT};
  selection-color:{TEXT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color:{ACCENT}; }}
QComboBox::drop-down {{ border:none; width:22px; }}
QComboBox QAbstractItemView {{ background:{PANEL}; border:1px solid {BORDER};
  border-radius:8px; selection-background-color:{SOFT};
  selection-color:{TEXT}; outline:none; }}
QTableWidget {{ background:{PANEL2}; border:1px solid {BORDER}; border-radius:12px;
  gridline-color:{SOFT}; selection-background-color:{SOFT};
  selection-color:{TEXT}; alternate-background-color:#fdfbff; }}
QTableWidget::item {{ padding:5px 7px; }}
QHeaderView::section {{ background:{SOFT2}; color:{MUTED}; border:none;
  border-right:1px solid {BORDER}; border-bottom:1px solid {BORDER};
  padding:10px 7px; font-weight:700; }}
QTabWidget::pane {{ border:1px solid {BORDER}; border-radius:12px; top:-1px;
  background:{PANEL}; }}
QTabBar::tab {{ background:transparent; color:{MUTED}; padding:11px 22px;
  border-bottom:3px solid transparent; font-weight:600; }}
QTabBar::tab:selected {{ color:{ACCENT_DARK}; border-bottom:3px solid {ACCENT}; }}
QTabBar::tab:hover {{ color:{ACCENT}; }}
QProgressBar {{ background:{SOFT2}; border:1px solid {BORDER}; border-radius:9px;
  text-align:center; height:24px; color:{TEXT}; font-weight:600; }}
QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
  stop:0 #a98cff, stop:1 {ACCENT}); border-radius:8px; }}
QTextBrowser, QTextEdit {{ background:{PANEL2}; border:1px solid {BORDER};
  border-radius:12px; padding:9px; }}
QCheckBox {{ spacing:9px; }}
QCheckBox::indicator {{ width:17px; height:17px; border-radius:6px;
  border:2px solid #d5cbf5; background:#ffffff; }}
QCheckBox::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QRadioButton::indicator {{ width:16px; height:16px; border-radius:8px;
  border:2px solid #d5cbf5; background:#ffffff; }}
QRadioButton::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; }}
QScrollBar:vertical {{ background:transparent; width:12px; margin:2px; }}
QScrollBar::handle:vertical {{ background:#ddd4f7; border-radius:6px; min-height:34px; }}
QScrollBar::handle:vertical:hover {{ background:#c9bbf2; }}
QScrollBar:horizontal {{ background:transparent; height:12px; margin:2px; }}
QScrollBar::handle:horizontal {{ background:#ddd4f7; border-radius:6px; min-width:34px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QToolTip {{ background:{PANEL}; color:{TEXT}; border:1px solid {ACCENT};
  border-radius:8px; padding:5px 8px; }}
"""


def risk_to_color(risk: str) -> QColor:
    return QColor(RISK_COLOR.get(risk, MUTED))


# ---------------------------------------------------------------- 应用图标
_APP_ICON_CACHE: dict[int, QIcon] = {}


def _asset_dir() -> Path:
    """资源目录：开发时在包内，打包后在 sys._MEIPASS 下。"""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "junkcleaner" / "assets"
    return Path(__file__).resolve().parent / "assets"


def app_icon(size: int = 0) -> QIcon:
    """加载应用图标（水晶盾牌）。

    打包后优先用 exe 内嵌图标（Windows 任务栏/Alt-Tab 用），
    开发时用 assets\\app.ico。
    """
    key = size
    cached = _APP_ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = QIcon()
    ico = _asset_dir() / "app.ico"
    if ico.exists():
        icon = QIcon(str(ico))
    if icon.isNull():
        # 兜底：用 exe 自身的图标（打包后一定存在）
        import sys
        exe = sys.executable
        if exe.lower().endswith(".exe") and os.path.exists(exe):
            icon = QIcon(exe)
    if icon.isNull():
        # 最后兜底：程序内绘制
        pm = QPixmap(256, 256)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(24, 24, 208, 208, 48, 48)
        p.setPen(QColor("#ffffff"))
        p.setFont(QFont("Microsoft YaHei UI", 110, QFont.Bold))
        p.drawText(pm.rect(), Qt.AlignCenter, "净")
        p.end()
        icon = QIcon(pm)
    if size:
        icon = QIcon(icon.pixmap(size, size))
    _APP_ICON_CACHE[key] = icon
    return icon


# ---------------------------------------------------------------- 工作线程
class ScanWorker(QThread):
    progress = Signal(str, float)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, include_disputed: bool = True) -> None:
        super().__init__()
        self.include_disputed = include_disputed

    def run(self) -> None:
        try:
            result = scanner.scan(
                progress=lambda s, r: self.progress.emit(s, r),
                include_disputed=self.include_disputed, compute_size=True)
            self.finished_ok.emit([f.to_dict() for f in result])
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class CleanWorker(QThread):
    log_line = Signal(str)
    progress = Signal(int, int, str)
    finished_ok = Signal(list)

    def __init__(self, findings: list[dict[str, Any]], uninstall: bool = True,
                 purge: bool = True) -> None:
        super().__init__()
        self.findings = findings
        self.uninstall = uninstall
        self.purge = purge

    def run(self) -> None:
        reports = []
        total = len(self.findings)
        for i, f in enumerate(self.findings, 1):
            self.progress.emit(i, total, f.get("name", ""))
            rep = cleaner.clean_finding(
                f, uninstall=self.uninstall, purge_files=self.purge,
                log=lambda m: self.log_line.emit(m))
            reports.append(rep.to_dict())
        self.finished_ok.emit(reports)


# ---------------------------------------------------------------- 主窗口
class GuardCheckWorker(QThread):
    """后台做守护自检（进程枚举约 1 秒，不能放主线程）。"""

    done = Signal(dict)

    def run(self) -> None:
        data: dict[str, Any] = {}
        try:
            data["installed"] = guard.autostart_installed()
        except Exception:  # noqa: BLE001
            data["installed"] = False
        try:
            data["external_running"] = guard.guard_process_running()
        except Exception:  # noqa: BLE001
            data["external_running"] = False
        try:
            data["status_running"] = bool(
                core.read_status().get("guard_running"))
        except Exception:  # noqa: BLE001
            data["status_running"] = False
        self.done.emit(data)


class DefenderApplyWorker(QThread):
    """后台执行 Defender 策略自动应用（内含 gpupdate，约 5 秒）。"""

    done = Signal(dict)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._page = None

    def run(self) -> None:
        data: dict[str, Any] = {}
        try:
            if not core.is_admin():
                self.done.emit({"skipped": "not-admin"})
                return
            cfg = core.load_config()
            if not cfg.get("defender_auto_apply"):
                self.done.emit({"skipped": "disabled"})
                return
            import junkcleaner.defender as _def
            preset = cfg.get("defender_preset", "balanced")
            r = _def.apply_preset(preset)
            data["applied"] = r.get("applied", 0)
            data["detail"] = (f"{_def.PRESET_LABEL.get(preset, preset)}："
                              f"应用 {r.get('applied', 0)} 项")
        except Exception as exc:  # noqa: BLE001
            data["error"] = str(exc)
        self.done.emit(data)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{__version__}")
        self.resize(1180, 760)

        self.all_findings: list[dict[str, Any]] = []
        self.scan_worker: ScanWorker | None = None
        self.clean_worker: CleanWorker | None = None
        self.guard_watcher: guard.InstallerWatcher | None = None

        self._build_tray()
        self._build_ui()
        self._refresh_admin_banner()
        self._load_existing()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        QTimer.singleShot(300, self._maybe_autostart_guard)
        QTimer.singleShot(1200, self._auto_apply_defender)

    def _auto_apply_defender(self) -> None:
        """启动时按配置自动应用 Defender 策略（需管理员 + 用户已开启）。

        这条路径内部会执行 `gpupdate /force`，实测约 5 秒。
        必须放后台，否则启动后 1.2 秒界面会卡死 5 秒。
        """
        self._defender_worker = DefenderApplyWorker(self)
        self._defender_worker.done.connect(self._on_defender_applied)
        self._defender_worker.start()

    def _on_defender_applied(self, data: dict) -> None:
        if data.get("error"):
            core.log(f"自动应用 Defender 策略失败: {data['error']}",
                     level="ERROR", source="defender")
        elif data.get("applied") and self.notify:
            self.notify("Defender 策略已自动优化", str(data.get("detail", "")))

    def _tick(self) -> None:
        """每两秒刷新守护状态与拦截记录。"""
        self._sync_guard_ui()
        if self.tabs.currentWidget() is not None and \
                self.tabs.tabText(self.tabs.currentIndex()) == "拦截守护":
            self.refresh_events()

    # ---------------- 托盘 ----------------
    def _make_icon(self, color: str = ACCENT) -> QIcon:
        """兼容旧调用：返回应用图标（水晶盾牌）。"""
        _ = color  # 保留参数签名，颜色不再影响图标
        return app_icon()

    def _rounded_logo(self, w: int, h: int) -> QPixmap:
        """把方形图标裁成圆角，放在淡紫卡片上更融合。"""
        src = app_icon().pixmap(w, h)
        out = QPixmap(w, h)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 11, 11)
        p.setClipPath(path)
        p.drawPixmap(0, 0, src)
        p.end()
        return out

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} 运行中")
        menu = QMenu()
        act_show = QAction("打开主界面", self)
        act_show.triggered.connect(self._show_window)
        act_scan = QAction("立即扫描", self)
        act_scan.triggered.connect(lambda: (self._show_window(), self.start_scan()))
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit_app)
        menu.addAction(act_show)
        menu.addAction(act_scan)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.setWindowIcon(self._make_icon())

    def notify(self, title: str, message: str) -> None:
        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(title, message, self._make_icon(), 6000)

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_hidden_to_tray(self) -> None:
        """开机自启入口：不显示主窗口，直接驻留右下角托盘。"""
        self.tray.show()
        self.hide()
        # 自启场景下自动开启拦截守护，否则“开机自启”没有实际防护效果
        try:
            cfg = core.load_config()
            if core.is_admin() and not (self.guard_watcher
                                        and self.guard_watcher.running):
                self._start_guard_thread()
            self.notify(APP_NAME, "已在后台运行，双击托盘图标打开主界面。")
        except Exception as exc:  # noqa: BLE001
            core.log(f"托盘启动守护失败: {exc}", level="WARN", source="gui")

    # ---------------- 界面骨架 ----------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        # 状态栏标签必须最先创建：各个页面在构造时就会通过回调调用
        # self.status_label.setText()，如果等到最后才建，页面构造阶段
        # 一旦触发 set_status 就会 AttributeError。
        if not hasattr(self, "status_label"):
            self.status_label = QLabel("就绪")
            self.status_label.setObjectName("Muted")
        if not hasattr(self, "admin_label"):
            self.admin_label = QLabel(
                "管理员" if core.is_admin() else "普通用户")
            self.admin_label.setObjectName("Muted")

        root.addWidget(self._header())
        self.admin_banner = self._banner()
        root.addWidget(self.admin_banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_scan(), "扫描与清理")
        self.tabs.addTab(self._tab_guard(), "拦截守护")
        self.trust_page = TrustPage(notify=self.notify,
                                    status=lambda m: self.status_label.setText(m))
        self.tabs.addTab(self.trust_page, "可信软件")
        self.memory_page = MemoryPage(notify=self.notify,
                                      status=lambda m: self.status_label.setText(m))
        self.tabs.addTab(self.memory_page, "内存优化")
        self.defender_page = DefenderPage(
            notify=self.notify, status=lambda m: self.status_label.setText(m))
        self.tabs.addTab(self.defender_page, "Defender 优化")
        self.tuning_page = TuningPage(
            notify=self.notify, status=lambda m: self.status_label.setText(m))
        self.tabs.addTab(self.tuning_page, "电源 / GPU")
        self.hardware_page = HardwarePage(
            notify=self.notify,
            status=lambda m: self.status_label.setText(m)
            if hasattr(self, "status_label") else None)
        self.tabs.addTab(self.hardware_page, "硬件检测")
        self.tabs.addTab(self._tab_quarantine(), "隔离与还原")
        self.tabs.addTab(self._tab_logs(), "运行日志")
        root.addWidget(self.tabs, 1)
        root.addWidget(self._statusbar())

    def _header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("Hero")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)

        logo = QLabel()
        logo.setPixmap(self._rounded_logo(46, 46))
        logo.setFixedSize(50, 50)
        lay.addWidget(logo)

        title = QLabel(APP_NAME)
        title.setObjectName("H1")
        sub = QLabel("垃圾 / 流氓软件识别 · 彻底卸载残留 · 实时安装拦截")
        sub.setObjectName("Muted")
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(title)
        col.addWidget(sub)
        lay.addLayout(col)
        lay.addStretch(1)

        self.guard_pill = QLabel("守护未运行")
        self.guard_pill.setObjectName("Pill")
        self.guard_pill.setStyleSheet(
            f"QLabel#Pill{{background:{SOFT};border:1px solid #ddd2fb;"
            f"border-radius:14px;padding:6px 15px;color:{MUTED};font-weight:700;}}")
        lay.addWidget(self.guard_pill)

        self.admin_pill = QLabel("管理员" if core.is_admin() else "普通用户")
        self.admin_pill.setStyleSheet(
            f"background:#ffffff;border:1px solid #ddd2fb;border-radius:14px;"
            f"padding:6px 15px;color:{GOOD if core.is_admin() else ROGUE};"
            f"font-weight:700;")
        lay.addWidget(self.admin_pill)
        return bar

    def _banner(self) -> QWidget:
        w = QFrame()
        w.setObjectName("Card")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 8, 14, 8)
        self.banner_label = QLabel("")
        btn = QPushButton("以管理员身份重启")
        btn.setObjectName("Primary")
        btn.clicked.connect(self._relaunch_admin)
        lay.addWidget(self.banner_label, 1)
        lay.addWidget(btn)
        w.setVisible(False)
        return w

    def _refresh_admin_banner(self) -> None:
        if core.is_admin():
            self.admin_banner.setVisible(False)
        else:
            self.admin_banner.setVisible(True)
            self.banner_label.setText(
                "当前不是管理员：卸载、删除服务/任务、拦截安装都需要管理员权限。")

    def _relaunch_admin(self) -> None:
        if core.relaunch_as_admin():
            QApplication.quit()
        else:
            QMessageBox.warning(self, "提权失败", "未能请求管理员权限，请右键以管理员身份运行。")

    # ---------------- 页 1：扫描 ----------------
    def _tab_scan(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        tools = QHBoxLayout()
        self.btn_scan = QPushButton("开始扫描")
        self.btn_scan.setObjectName("Primary")
        self.btn_scan.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.btn_scan.clicked.connect(self.start_scan)
        self.btn_clean = QPushButton("清理选中项")
        self.btn_clean.setObjectName("Danger")
        self.btn_clean.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.btn_clean.clicked.connect(self.clean_selected)
        self.btn_clean.setEnabled(False)
        self.btn_selall = QPushButton("全选")
        self.btn_selall.clicked.connect(lambda: self._set_all_checked(True))
        self.btn_selnone = QPushButton("全不选")
        self.btn_selnone.clicked.connect(lambda: self._set_all_checked(False))
        self.btn_trust = QPushButton("信任此软件")
        self.btn_trust.setObjectName("Ghost")
        self.btn_trust.setToolTip("把选中的软件加入可信白名单，之后扫描与实时防护都会跳过它")
        self.btn_trust.clicked.connect(self.trust_selected_findings)
        self.filter_risk = QComboBox()
        self.filter_risk.addItems(["全部等级", "仅流氓", "仅捆绑", "仅争议"])
        self.filter_risk.currentIndexChanged.connect(self._apply_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("按名称 / 厂商过滤…")
        self.search.textChanged.connect(self._apply_filter)
        self.check_purge = QCheckBox("清理残留文件")
        self.check_purge.setChecked(True)
        self.check_uninstall = QCheckBox("执行卸载程序")
        self.check_uninstall.setChecked(True)
        self.cmb_intensity = QComboBox()
        self.cmb_intensity.addItem("低占用（游戏/办公时）", "low")
        self.cmb_intensity.addItem("均衡", "medium")
        self.cmb_intensity.addItem("快速（不计占用）", "high")
        self.cmb_intensity.setToolTip(
            "低占用模式会降低进程优先级并放慢扫描节奏，尽量不影响日常工作与游戏")
        idx = self.cmb_intensity.findData(core.scan_intensity())
        self.cmb_intensity.setCurrentIndex(idx if idx >= 0 else 0)
        self.cmb_intensity.currentIndexChanged.connect(
            lambda: core.update_config(scan_intensity=self.cmb_intensity.currentData()))

        tools.addWidget(self.btn_scan)
        tools.addWidget(self.btn_clean)
        tools.addSpacing(8)
        tools.addWidget(self.btn_selall)
        tools.addWidget(self.btn_selnone)
        tools.addWidget(self.btn_trust)
        tools.addStretch(1)
        lay.addLayout(tools)

        tools2 = QHBoxLayout()
        tools2.setSpacing(8)
        self.filter_risk.setMinimumWidth(120)
        self.search.setMinimumWidth(180)
        self.cmb_intensity.setMinimumWidth(150)
        self.check_uninstall.setMinimumWidth(120)
        self.check_purge.setMinimumWidth(120)
        tools2.addWidget(self.filter_risk)
        tools2.addWidget(self.search, 1)
        tools2.addWidget(QLabel("性能"))
        tools2.addWidget(self.cmb_intensity)
        tools2.addWidget(self.check_uninstall)
        tools2.addWidget(self.check_purge)
        lay.addLayout(tools2)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("就绪")
        lay.addWidget(self.progress)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "名称", "等级", "厂商", "证据", "占用"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 34)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 76)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 170)
        h.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 80)
        h.setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.setColumnWidth(5, 100)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.table.itemChanged.connect(lambda _i: self._update_clean_button())
        split.addWidget(self.table)

        self.detail = QTextBrowser()
        self.detail.setMinimumHeight(170)
        self.detail.setHtml(self._detail_placeholder())
        split.addWidget(self.detail)
        split.setSizes([430, 200])
        lay.addWidget(split, 1)
        return page

    def _detail_placeholder(self) -> str:
        return (f"<div style='color:{MUTED};font-family:Microsoft YaHei UI'>"
                "选择上方任意一行，查看判定证据（卸载项 / 进程 / 服务 / "
                "计划任务 / 安装目录），确认后再执行清理。</div>")

    # ---------------- 页 2：守护 ----------------
    def _tab_guard(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(12)

        top = QHBoxLayout()
        box = QGroupBox("实时防护")
        g = QGridLayout(box)
        self.btn_guard = QPushButton("启动拦截")
        self.btn_guard.setObjectName("Primary")
        self.btn_guard.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.btn_guard.clicked.connect(self.toggle_guard)
        self.check_autostart = QCheckBox("开机自动启动（静默到右下角托盘）")
        self.check_autostart.toggled.connect(self._toggle_autostart)
        self.check_autoq = QCheckBox("自动隔离疑似下载站捆绑安装器")
        self.check_autoq.setChecked(True)
        self.check_autoq.toggled.connect(
            lambda v: core.update_config(auto_quarantine_installer=v))
        self.spin_interval = QSpinBox()
        self.spin_interval.setRange(1, 30)
        self.spin_interval.setSuffix(" 秒")
        self.spin_interval.setValue(2)
        self.spin_interval.valueChanged.connect(self._set_interval)
        g.addWidget(self.btn_guard, 0, 0, 1, 2)
        g.addWidget(self.check_autostart, 1, 0, 1, 2)
        g.addWidget(self.check_autoq, 2, 0, 1, 2)
        g.addWidget(QLabel("轮询间隔"), 3, 0)
        g.addWidget(self.spin_interval, 3, 1)
        top.addWidget(box, 1)

        stats = QGroupBox("运行状态")
        gs = QGridLayout(stats)
        self.stat_state = QLabel("未运行")
        self.stat_state.setObjectName("Stat")
        self.stat_blocked = QLabel("0")
        self.stat_blocked.setObjectName("Stat")
        self.stat_quar = QLabel("0")
        self.stat_quar.setObjectName("Stat")
        self.stat_mode = QLabel("—")
        self.stat_mode.setObjectName("Muted")
        gs.addWidget(QLabel("守护状态"), 0, 0)
        gs.addWidget(self.stat_state, 0, 1)
        gs.addWidget(QLabel("防护模式"), 0, 2)
        gs.addWidget(self.stat_mode, 0, 3)
        gs.addWidget(QLabel("已拦截运行"), 1, 0)
        gs.addWidget(self.stat_blocked, 1, 1)
        gs.addWidget(QLabel("已隔离安装包"), 1, 2)
        gs.addWidget(self.stat_quar, 1, 3)
        self.stat_autostart = QLabel("—")
        self.stat_autostart.setObjectName("Muted")
        gs.addWidget(QLabel("开机自启"), 2, 0)
        gs.addWidget(self.stat_autostart, 2, 1, 1, 3)
        top.addWidget(stats, 1)

        custom = QGroupBox("自定义拦截（按文件名关键词）")
        gc = QGridLayout(custom)
        self.custom_input = QLineEdit()
        self.custom_input.setPlaceholderText("例如：某某安装器")
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add_custom)
        gc.addWidget(self.custom_input, 0, 0)
        gc.addWidget(btn_add, 0, 1)
        self.custom_list = QComboBox()
        gc.addWidget(self.custom_list, 1, 0)
        btn_del = QPushButton("删除")
        btn_del.setObjectName("Ghost")
        btn_del.clicked.connect(self._remove_custom)
        gc.addWidget(btn_del, 1, 1)
        top.addWidget(custom, 1)

        ignore = QGroupBox("忽略名单（无条件放行，只记录不拦截）")
        gi = QGridLayout(ignore)
        self.ignore_input = QLineEdit()
        self.ignore_input.setPlaceholderText("进程名或路径关键词，例如 wps.exe")
        btn_iadd = QPushButton("添加")
        btn_iadd.clicked.connect(self._add_ignore)
        self.ignore_list = QComboBox()
        gc_btn = QPushButton("删除")
        gc_btn.setObjectName("Ghost")
        gc_btn.clicked.connect(self._remove_ignore)
        gi.addWidget(self.ignore_input, 0, 0)
        gi.addWidget(btn_iadd, 0, 1)
        gi.addWidget(self.ignore_list, 1, 0)
        gi.addWidget(gc_btn, 1, 1)
        top.addWidget(ignore, 1)
        lay.addLayout(top)

        events_box = QGroupBox("拦截记录")
        ev = QVBoxLayout(events_box)
        self.events_table = QTableWidget(0, 5)
        self.events_table.setHorizontalHeaderLabels(["时间", "类型", "对象", "原因", "结果"])
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.events_table.setSelectionBehavior(QTableWidget.SelectRows)
        eh = self.events_table.horizontalHeader()
        for i, w in enumerate([150, 110, 280, 300]):
            eh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.events_table.setColumnWidth(i, w)
        eh.setSectionResizeMode(4, QHeaderView.Stretch)
        ev.addWidget(self.events_table)
        btn_refresh = QPushButton("刷新记录")
        btn_refresh.setObjectName("Ghost")
        btn_refresh.clicked.connect(self.refresh_events)
        ev.addWidget(btn_refresh, 0, Qt.AlignRight)
        lay.addWidget(events_box, 1)
        return page

    # ---------------- 页 3：隔离 ----------------
    def _tab_quarantine(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)
        info = QLabel("被清理的残留文件与拦截的安装包都保存在隔离区，可随时还原；"
                      "卸载程序本身不可逆。")
        info.setObjectName("Muted")
        lay.addWidget(info)
        # 隔离区位置：可选其它盘/文件夹，避免默认全在 C 盘
        loc_row = QHBoxLayout()
        self.lbl_quar_dir = QLabel("")
        self.lbl_quar_dir.setObjectName("Muted")
        self.lbl_quar_dir.setWordWrap(True)
        btn_pick = QPushButton("选择隔离区文件夹")
        btn_pick.setObjectName("Ghost")
        btn_pick.clicked.connect(self._choose_quarantine_dir)
        btn_pick_reset = QPushButton("恢复默认")
        btn_pick_reset.setObjectName("Ghost")
        btn_pick_reset.clicked.connect(self._reset_quarantine_dir)
        loc_row.addWidget(QLabel("隔离区位置"))
        loc_row.addWidget(self.lbl_quar_dir, 1)
        loc_row.addWidget(btn_pick)
        loc_row.addWidget(btn_pick_reset)
        lay.addLayout(loc_row)
        self._refresh_quarantine_dir()
        btn_row = QHBoxLayout()
        btn_open = QPushButton("打开隔离区文件夹")
        btn_open.setObjectName("Ghost")
        btn_open.clicked.connect(lambda: core.open_folder(core.quarantine_dir()))
        btn_re = QPushButton("还原选中记录")
        btn_re.clicked.connect(self._restore_selected)
        btn_ref = QPushButton("刷新")
        btn_ref.setObjectName("Ghost")
        btn_ref.clicked.connect(self.refresh_manifests)
        btn_row.addWidget(btn_open)
        btn_row.addWidget(btn_re)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_ref)
        lay.addLayout(btn_row)

        self.manifest_table = QTableWidget(0, 5)
        self.manifest_table.setHorizontalHeaderLabels(
            ["时间", "软件", "可还原文件", "已释放", "清单"])
        self.manifest_table.verticalHeader().setVisible(False)
        self.manifest_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.manifest_table.setSelectionBehavior(QTableWidget.SelectRows)
        mh = self.manifest_table.horizontalHeader()
        for i, w in enumerate([160, 260, 110, 110]):
            mh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.manifest_table.setColumnWidth(i, w)
        mh.setSectionResizeMode(4, QHeaderView.Stretch)
        lay.addWidget(self.manifest_table, 1)
        return page

    # ---------------- 页 4：日志 ----------------
    def _tab_logs(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 12, 12, 12)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        lay.addWidget(self.log_view, 1)
        row = QHBoxLayout()
        b1 = QPushButton("刷新日志")
        b1.setObjectName("Ghost")
        b1.clicked.connect(self.refresh_logs)
        b2 = QPushButton("打开数据目录")
        b2.setObjectName("Ghost")
        b2.clicked.connect(lambda: core.open_folder(core.data_dir()))
        row.addStretch(1)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        return page

    def _statusbar(self) -> QWidget:
        w = QFrame()
        w.setObjectName("Card")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 6, 12, 6)
        # 这两个标签在 _build_ui 开头就已创建，这里只负责摆放
        lay.addWidget(self.status_label, 1)
        lay.addWidget(self.admin_label)
        return w

    # ---------------- 扫描逻辑 ----------------
    def start_scan(self) -> None:
        if self.scan_worker and self.scan_worker.isRunning():
            return
        self.tabs.setCurrentIndex(0)
        self.btn_scan.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.progress.setValue(0)
        self.table.setRowCount(0)
        self.status_label.setText("正在扫描…")
        self.scan_worker = ScanWorker(include_disputed=True)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.finished_ok.connect(self._on_scan_done)
        self.scan_worker.failed.connect(self._on_scan_failed)
        self.scan_worker.start()

    def _on_scan_progress(self, stage: str, ratio: float) -> None:
        self.progress.setValue(int(ratio * 100))
        self.progress.setFormat(f"{stage}  {int(ratio * 100)}%")
        self.status_label.setText(stage)

    def _on_scan_failed(self, message: str) -> None:
        self.btn_scan.setEnabled(True)
        self.progress.setFormat("扫描失败")
        QMessageBox.critical(self, "扫描失败", message)

    def _on_scan_done(self, findings: list[dict[str, Any]]) -> None:
        self.btn_scan.setEnabled(True)
        self.all_findings = findings
        self.progress.setValue(100)
        count = len(findings)
        total_size = sum(int(f.get("computed_size", 0)) for f in findings)
        self.progress.setFormat(f"完成：命中 {count} 项")
        self.status_label.setText(
            f"扫描完成：命中 {count} 个家族，估算占用 {core.human_size(total_size)}")
        self._apply_filter()
        self._update_clean_button()
        if count:
            self.notify("扫描完成", f"发现 {count} 项可清理的垃圾/流氓软件。")

    def _apply_filter(self) -> None:
        if not self.all_findings:
            self.table.setRowCount(0)
            self._update_clean_button()
            return
        idx = self.filter_risk.currentIndex() if hasattr(self, "filter_risk") else 0
        wanted = {0: None, 1: "rogue", 2: "bundle", 3: "disputed"}.get(idx)
        text = self.search.text().strip().lower() if hasattr(self, "search") else ""
        rows = []
        for f in self.all_findings:
            if wanted and f.get("risk") != wanted:
                continue
            if text and text not in (f.get("name", "") + f.get("vendor", "")).lower():
                continue
            rows.append(f)
        self.table.setRowCount(0)
        self.table.setRowCount(len(rows))
        for r, f in enumerate(rows):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if f.get("selected") else Qt.Unchecked)
            chk.setData(Qt.UserRole, f)
            self.table.setItem(r, 0, chk)
            name = QTableWidgetItem(f.get("name", ""))
            name.setData(Qt.UserRole, f)
            if f.get("risk") == "rogue":
                name.setForeground(risk_to_color("rogue"))
            self.table.setItem(r, 1, name)
            if f.get("trusted"):
                if f.get("known_normal"):
                    risk = QTableWidgetItem("正常软件")
                    risk.setForeground(QColor("#7dd3fc"))
                else:
                    risk = QTableWidgetItem("可信")
                    risk.setForeground(QColor(GOOD))
            else:
                risk = QTableWidgetItem(RISK_TEXT.get(f.get("risk"), "?"))
                risk.setForeground(risk_to_color(f.get("risk", "")))
            risk.setData(Qt.UserRole, f)
            self.table.setItem(r, 2, risk)
            self.table.setItem(r, 3, QTableWidgetItem(f.get("vendor", "")))
            self.table.setItem(r, 4, QTableWidgetItem(str(self._evidence_count(f))))
            self.table.setItem(r, 5, QTableWidgetItem(
                core.human_size(f.get("computed_size", 0))))
        self.table.resizeRowsToContents()

    @staticmethod
    def _evidence_count(f: dict[str, Any]) -> int:
        return (len(f.get("uninstall_entries") or []) + len(f.get("processes") or [])
                + len(f.get("services") or []) + len(f.get("tasks") or [])
                + len(f.get("paths") or []) + len(f.get("startup") or []))

    def _set_all_checked(self, value: bool) -> None:
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item:
                item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_clean_button()

    def _selected_findings(self) -> list[dict[str, Any]]:
        out = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return [f for f in out if f]

    def trust_selected_findings(self) -> None:
        """把勾选的扫描结果加入可信白名单（含 Defender 可选项）。"""
        picks = self._selected_findings()
        if not picks:
            QMessageBox.information(self, "未选择", "请先勾选要信任的软件。")
            return
        names = "、".join(f.get("name", "") for f in picks[:5])
        if len(picks) > 5:
            names += f" 等 {len(picks)} 项"
        if QMessageBox.question(
                self, "加入可信白名单",
                f"将 {names} 加入白名单？\n\n"
                "之后扫描与实时防护都会跳过这些软件，不再清理或拦截它们。"
        ) != QMessageBox.Yes:
            return
        added = 0
        for f in picks:
            target = ""
            for e in f.get("uninstall_entries") or []:
                if e.get("install_location"):
                    target = e["install_location"]
                    break
            if not target and f.get("paths"):
                target = f["paths"][0]
            if not target:
                for p in f.get("processes") or []:
                    if p.get("exe"):
                        target = p["exe"]
                        break
            if target:
                trust.add_trust(f.get("name", ""), "path", target, source="scan")
            else:
                trust.add_trust(f.get("name", ""), "name", f.get("name", ""), source="scan")
            added += 1
        # 立即更新列表状态
        for f in self.all_findings:
            if f.get("sig_id") in {p.get("sig_id") for p in picks}:
                f["trusted"] = True
                f["selected"] = False
                f["trusted_by"] = "手动信任"
        self._apply_filter()
        self._update_clean_button()
        if hasattr(self, "trust_page"):
            self.trust_page.refresh()
        QMessageBox.information(self, "完成", f"已将 {added} 个软件加入可信白名单。")

    def _update_clean_button(self) -> None:
        n = len(self._selected_findings())
        busy = bool(self.clean_worker and self.clean_worker.isRunning())
        self.btn_clean.setEnabled(bool(n) and not busy)
        self.btn_clean.setText(f"清理选中项 ({n})" if n else "清理选中项")

    def _show_detail(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.detail.setHtml(self._detail_placeholder())
            return
        item = self.table.item(rows[0].row(), 0)
        if item:
            self.detail.setHtml(self._render_detail(item.data(Qt.UserRole)))

    def _render_detail(self, f: dict[str, Any]) -> str:
        if not f:
            return self._detail_placeholder()
        risk = f.get("risk", "")
        color = RISK_COLOR.get(risk, MUTED)
        parts = ["<div style='font-family:Microsoft YaHei UI'>"]
        parts.append(f"<h3 style='color:{color};margin:0'>{f.get('name','')} "
                     f"<span style='color:{MUTED};font-size:12px'>"
                     f"[{RISK_TEXT.get(risk,'?')}] {f.get('vendor','')}</span></h3>")
        parts.append(f"<p style='color:{MUTED};margin:6px 0'>{f.get('why','')}</p>")
        parts.append(f"<p style='color:{ACCENT};margin:4px 0'>标签："
                     f"{' / '.join(f.get('tags') or []) or '—'}</p>")
        if f.get("trusted"):
            if f.get("known_normal"):
                parts.append(f"<p style='color:#7dd3fc;margin:4px 0'><b>已知正常软件</b>："
                             "本体正常使用，不会被清理。它若拉起第三方捆绑安装包，"
                             "实时防护会单独拦截。</p>")
            else:
                parts.append(f"<p style='color:{GOOD};margin:4px 0'><b>已加入可信白名单</b>"
                             f"（{f.get('trusted_by','')}），不会被清理或拦截。</p>")
        if f.get("basis"):
            parts.append(f"<p style='color:{MUTED};margin:4px 0'>判定依据：{f['basis']}</p>")

        def section(title: str, items: list[str]) -> None:
            if not items:
                return
            parts.append(f"<p style='color:{TEXT};margin:8px 0 2px'><b>{title}"
                         f"（{len(items)}）</b></p><ul style='margin:0 0 0 18px;color:{MUTED}'>")
            for it in items[:12]:
                parts.append(f"<li>{it}</li>")
            if len(items) > 12:
                parts.append(f"<li>… 其余 {len(items) - 12} 项</li>")
            parts.append("</ul>")

        section("卸载注册表项", [
            f"{e.get('display_name','')}　{e.get('publisher','')}　{e.get('version','')}"
            for e in f.get("uninstall_entries") or []])
        section("运行中进程", [
            f"{p.get('name','')} (PID {p.get('pid')})　{p.get('exe','')}"
            for p in f.get("processes") or []])
        section("系统服务", [
            f"{s.get('name','')}　{s.get('display','')}　[{s.get('state','')}]"
            for s in f.get("services") or []])
        section("计划任务", list(f.get("tasks") or []))
        section("开机自启", list(f.get("startup") or []))
        section("安装目录", list(f.get("paths") or []))
        parts.append("</div>")
        return "".join(parts)

    # ---------------- 清理逻辑 ----------------
    def clean_selected(self) -> None:
        selections = self._selected_findings()
        if not selections:
            return
        names = "、".join(f.get("name", "") for f in selections[:6])
        if len(selections) > 6:
            names += f" 等 {len(selections)} 项"
        do_uninstall = self.check_uninstall.isChecked()
        do_purge = self.check_purge.isChecked()
        msg = (f"即将处理 {len(selections)} 项：\n\n{names}\n\n"
               f"· 执行官方卸载程序：{'是' if do_uninstall else '否'}\n"
               f"· 隔离残留文件：{'是' if do_purge else '否'}\n\n"
               "残留文件会移入隔离区，可随时还原；卸载程序本身不可逆。是否继续？")
        if QMessageBox.question(self, "确认清理", msg) != QMessageBox.Yes:
            return
        self.btn_clean.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.log_view.clear()
        self.clean_worker = CleanWorker(selections, uninstall=do_uninstall, purge=do_purge)
        self.clean_worker.log_line.connect(self._on_clean_log)
        self.clean_worker.progress.connect(self._on_clean_progress)
        self.clean_worker.finished_ok.connect(self._on_clean_done)
        self.clean_worker.start()

    def _on_clean_log(self, line: str) -> None:
        self.log_view.append(line)

    def _on_clean_progress(self, i: int, total: int, name: str) -> None:
        self.progress.setValue(int(i / max(total, 1) * 100))
        self.progress.setFormat(f"正在清理 {i}/{total}：{name}")
        self.status_label.setText(f"正在清理：{name}")

    def _on_clean_done(self, reports: list[dict[str, Any]]) -> None:
        self.btn_scan.setEnabled(True)
        self._update_clean_button()
        freed = sum(int(r.get("freed_bytes", 0)) for r in reports)
        ok = sum(int(r.get("ok_count", 0)) for r in reports)
        fail = sum(int(r.get("fail_count", 0)) for r in reports)
        self.progress.setValue(100)
        self.progress.setFormat("清理完成")
        self.status_label.setText(
            f"清理完成：成功 {ok} 步，失败 {fail} 步，隔离 {core.human_size(freed)}")
        self.notify("清理完成",
                    f"完成 {len(reports)} 项，成功 {ok} 步，失败 {fail} 步。")
        self.refresh_manifests()
        done_ids = {r.get("sig_id") for r in reports}
        self.all_findings = [f for f in self.all_findings
                             if f.get("sig_id") not in done_ids]
        self._apply_filter()
        if fail:
            QMessageBox.information(
                self, "清理完成",
                f"成功 {ok} 步，失败 {fail} 步。\n失败通常是卸载程序需要交互或文件被占用，"
                "可在日志页查看详情，或重启后再次扫描。")
        else:
            QMessageBox.information(self, "清理完成", f"成功 {ok} 步，全部处理完毕。")

    # ---------------- 守护逻辑 ----------------
    def _maybe_autostart_guard(self) -> None:
        """启动时的守护自检。

        `guard_process_running()` 要遍历所有进程并读命令行，
        实测约 1 秒；`guard.stop_external_guards()` 类似。
        这些必须放后台，否则启动瞬间界面会卡住。
        """
        if self.guard_watcher is None:
            self.guard_watcher = guard.InstallerWatcher(notify=self.notify)
        # 读配置很快，直接在主线程完成
        cfg = core.load_config()
        self.spin_interval.blockSignals(True)
        self.spin_interval.setValue(int(cfg.get("guard_interval", 2) or 2))
        self.spin_interval.blockSignals(False)
        self.check_autoq.blockSignals(True)
        self.check_autoq.setChecked(bool(cfg.get("auto_quarantine_installer", True)))
        self.check_autoq.blockSignals(False)
        self._refresh_custom_list()
        self._refresh_ignore_list()
        self.refresh_events()
        # 重活（进程枚举 + 自启检测）放后台
        self._guard_check = GuardCheckWorker(self)
        self._guard_check.done.connect(self._on_guard_checked)
        self._guard_check.start()

    def _on_guard_checked(self, data: dict) -> None:
        try:
            self.check_autostart.blockSignals(True)
            self.check_autostart.setChecked(bool(data.get("installed")))
            self.check_autostart.blockSignals(False)
        except Exception:  # noqa: BLE001
            pass
        if data.get("external_running") or data.get("status_running"):
            self._start_guard_thread()
        else:
            self._sync_guard_ui()

    def _start_guard_thread(self) -> None:
        # 若计划任务已在后台运行，先接管，避免两个守护同时工作
        if guard.guard_process_running():
            guard.stop_external_guards()
        if self.guard_watcher is None:
            self.guard_watcher = guard.InstallerWatcher(notify=self.notify)
        self.guard_watcher.interval = float(self.spin_interval.value())
        self.guard_watcher.start()
        self._sync_guard_ui()

    def toggle_guard(self) -> None:
        if self.guard_watcher and self.guard_watcher.running:
            self.guard_watcher.stop()
        else:
            if not core.is_admin():
                QMessageBox.warning(self, "需要管理员权限",
                                    "拦截安装、结束进程需要管理员权限，请先以管理员身份重启。")
                return
            self._start_guard_thread()
        self._sync_guard_ui()

    def _sync_guard_ui(self) -> None:
        running = bool(self.guard_watcher and self.guard_watcher.running)
        self.btn_guard.setText("停止拦截" if running else "启动拦截")
        self.btn_guard.setObjectName("Danger" if running else "Primary")
        self.btn_guard.setIcon(self.style().standardIcon(
            QStyle.SP_MediaStop if running else QStyle.SP_MediaPlay))
        self.btn_guard.style().unpolish(self.btn_guard)
        self.btn_guard.style().polish(self.btn_guard)
        self.stat_state.setText("运行中" if running else "未运行")
        self.stat_state.setStyleSheet(f"color:{GOOD if running else MUTED}")
        self.guard_pill.setText("守护运行中" if running else "守护未运行")
        self.guard_pill.setStyleSheet(
            f"QLabel#Pill{{background:{'#e2fbf4' if running else SOFT};"
            f"border:1px solid {'#b9ecdc' if running else '#ddd2fb'};"
            f"border-radius:14px;padding:6px 15px;"
            f"color:{GOOD if running else MUTED};font-weight:700;}}")
        if running and self.guard_watcher:
            self.stat_blocked.setText(str(self.guard_watcher.stats.get("blocked", 0)))
            self.stat_quar.setText(str(self.guard_watcher.stats.get("quarantined", 0)))
            self.stat_mode.setText(self.guard_watcher.stats.get("mode", "—"))
        info = guard.autostart_info() if self.check_autostart.isChecked() else {}
        if info:
            self.stat_autostart.setText(
                f"{info.get('State','')}（登录自启 → 静默托盘）")
        elif self.check_autostart.isChecked():
            self.stat_autostart.setText("已启用")
        else:
            self.stat_autostart.setText("未开启")

    def _set_interval(self, value: int) -> None:
        core.update_config(guard_interval=value)
        if self.guard_watcher:
            self.guard_watcher.interval = float(value)

    def _toggle_autostart(self, checked: bool) -> None:
        if checked:
            ok, _ = guard.install_autostart()
            if not ok:
                QMessageBox.warning(self, "设置失败",
                                    "写入开机启动项失败，请确认有权限写入注册表。")
                self.check_autostart.blockSignals(True)
                self.check_autostart.setChecked(False)
                self.check_autostart.blockSignals(False)
        else:
            guard.remove_autostart()

    def _add_custom(self) -> None:
        text = self.custom_input.text().strip()
        if not text:
            return
        cfg = core.load_config()
        names = list(cfg.get("custom_block_names") or [])
        if text not in names:
            names.append(text)
        core.update_config(custom_block_names=names)
        self.custom_input.clear()
        self._refresh_custom_list()
        self.status_label.setText(f"已添加自定义拦截：{text}")

    def _remove_custom(self) -> None:
        name = self.custom_list.currentText().strip()
        if not name:
            return
        cfg = core.load_config()
        names = [n for n in (cfg.get("custom_block_names") or []) if n != name]
        core.update_config(custom_block_names=names)
        self._refresh_custom_list()
        self.status_label.setText(f"已删除自定义拦截：{name}")

    def _refresh_custom_list(self) -> None:
        self.custom_list.clear()
        self.custom_list.addItems(core.load_config().get("custom_block_names") or [])

    def _add_ignore(self) -> None:
        text = self.ignore_input.text().strip()
        if not text:
            return
        cfg = core.load_config()
        names = list(cfg.get("guard_ignore_names") or [])
        if text not in names:
            names.append(text)
        core.update_config(guard_ignore_names=names)
        self.ignore_input.clear()
        self._refresh_ignore_list()
        self.status_label.setText(f"已加入忽略名单：{text}")

    def _remove_ignore(self) -> None:
        name = self.ignore_list.currentText().strip()
        if not name:
            return
        cfg = core.load_config()
        names = [n for n in (cfg.get("guard_ignore_names") or []) if n != name]
        core.update_config(guard_ignore_names=names)
        self._refresh_ignore_list()
        self.status_label.setText(f"已从忽略名单删除：{name}")

    def _refresh_ignore_list(self) -> None:
        self.ignore_list.clear()
        self.ignore_list.addItems(core.load_config().get("guard_ignore_names") or [])

    def refresh_events(self) -> None:
        events = core.read_events(300)
        self.events_table.setRowCount(len(events))
        kind_text = {"block_installer": "隔离安装包", "block_process": "拦截运行",
                     "clean": "清理", "scan": "扫描"}
        for r, e in enumerate(events):
            self.events_table.setItem(r, 0, QTableWidgetItem(e.get("time", "")))
            self.events_table.setItem(r, 1, QTableWidgetItem(
                kind_text.get(e.get("kind", ""), e.get("kind", ""))))
            obj = e.get("file") or e.get("exe") or e.get("name", "")
            self.events_table.setItem(r, 2, QTableWidgetItem(str(obj)))
            self.events_table.setItem(r, 3, QTableWidgetItem(str(e.get("reason", ""))))
            ok = e.get("ok")
            result = "成功" if ok else ("失败" if ok is False else "")
            item = QTableWidgetItem(result)
            item.setForeground(QColor(GOOD if ok else ROGUE))
            self.events_table.setItem(r, 4, item)

    # ---------------- 隔离区 ----------------
    def _refresh_quarantine_dir(self) -> None:
        custom = str(core.load_config().get("quarantine_dir") or "").strip()
        cur = core.quarantine_dir()
        self.lbl_quar_dir.setText(
            f"{cur}" + ("" if custom else "（默认）"))

    def _choose_quarantine_dir(self) -> None:
        cur = str(core.quarantine_dir())
        chosen = QFileDialog.getExistingDirectory(
            self, "选择隔离区文件夹", cur,
            QFileDialog.Option.ShowDirsOnly)
        if not chosen:
            return
        # 校验可写，避免选到只读位置后清理/拦截静默失败
        from pathlib import Path as _P
        target = _P(chosen) / "JunkCleanerQuarantine"
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "目录不可用",
                                f"该位置无法写入：{exc}")
            return
        core.update_config(quarantine_dir=str(target))
        core.log(f"隔离区目录已改为 {target}", source="gui")
        self._refresh_quarantine_dir()
        QMessageBox.information(
            self, "已设置",
            f"隔离区已改为：\n{target}\n\n"
            "之后清理的残留与拦截的安装包都会放到这里。")

    def _reset_quarantine_dir(self) -> None:
        core.update_config(quarantine_dir="")
        self._refresh_quarantine_dir()
    def refresh_manifests(self) -> None:
        manifests = cleaner.list_manifests()
        self.manifest_table.setRowCount(len(manifests))
        for r, m in enumerate(manifests):
            self.manifest_table.setItem(r, 0, QTableWidgetItem(m.get("time", "")))
            self.manifest_table.setItem(r, 1, QTableWidgetItem(m.get("name", "")))
            self.manifest_table.setItem(r, 2, QTableWidgetItem(str(m.get("_moves", 0))))
            self.manifest_table.setItem(r, 3, QTableWidgetItem(
                core.human_size(m.get("_size", 0))))
            item = QTableWidgetItem(m.get("_file", ""))
            item.setData(Qt.UserRole, m.get("_file", ""))
            self.manifest_table.setItem(r, 4, item)

    def _restore_selected(self) -> None:
        rows = self.manifest_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "未选择", "请先选择一条清理记录。")
            return
        path = self.manifest_table.item(rows[0].row(), 4).data(Qt.UserRole)
        if not path:
            return
        if QMessageBox.question(self, "确认还原",
                                "将把该记录隔离的文件还原到原位置，是否继续？") != QMessageBox.Yes:
            return
        actions = cleaner.restore_manifest(path)
        ok = sum(1 for a in actions if a.ok)
        QMessageBox.information(self, "还原完成", f"成功还原 {ok} / {len(actions)} 项。")
        self.refresh_manifests()

    def refresh_logs(self) -> None:
        lines = core.read_recent_logs(500)
        self.log_view.setPlainText("\n".join(lines))
        from PySide6.QtGui import QTextCursor
        self.log_view.moveCursor(QTextCursor.End)

    # ---------------- 启动 / 退出 ----------------
    def _load_existing(self) -> None:
        existing = scanner.load_last_scan()
        if existing:
            self.all_findings = existing
            self._apply_filter()
            self._update_clean_button()
            self.status_label.setText(f"已载入上次扫描结果：{len(existing)} 项")
        self.refresh_manifests()
        self.refresh_events()
        self.refresh_logs()

    def _quit_app(self) -> None:
        if self.guard_watcher and self.guard_watcher.running:
            self.guard_watcher.stop()
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        self.trust_page.shutdown()
        self.memory_page.shutdown()
        # 启动时的后台任务（守护自检 / Defender 策略应用）也要等结束。
        # 其中 Defender 应用内部会跑 gpupdate（约 5 秒），
        # 线程未收尾就退出会让进程以 0xc0000409 崩溃。
        for attr in ("_guard_check", "_defender_worker"):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if w.isRunning():
                    w.wait(8000)
            except Exception:  # noqa: BLE001
                pass
        # 这两个页面有后台刷新线程，必须等它们结束再退出，
        # 否则线程存活时销毁窗口会导致进程异常退出（0xc0000409）。
        try:
            self.tuning_page.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.hardware_page.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.defender_page.shutdown()
        except Exception:  # noqa: BLE001
            pass
        if self.guard_watcher and self.guard_watcher.running:
            self.hide()
            self.tray.show()
            self.notify(APP_NAME, "已最小化到托盘，拦截守护继续运行。")
            event.ignore()
            return
        event.accept()


def run_gui(argv: list[str] | None = None) -> int:
    from . import core as _core
    _set_app_user_model_id()
    app = QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    # 设置应用级图标：任务栏、Alt-Tab、窗口标题栏都用水晶盾牌
    icon = app_icon()
    app.setWindowIcon(icon)
    win = MainWindow()
    win.setWindowIcon(icon)
    import os
    try:
        tab = int(os.environ.get("JUNKCLEANER_TAB", "0"))
        if 0 <= tab < win.tabs.count():
            win.tabs.setCurrentIndex(tab)
    except ValueError:
        pass
    # 开机自启（--tray）：不弹主窗口，直接静默到右下角托盘常驻。
    if os.environ.get("JUNKCLEANER_START_TRAY") == "1":
        # 隐藏到托盘时不能因为“没有可见窗口”就退出。
        app.setQuitOnLastWindowClosed(False)
        win.start_hidden_to_tray()
    else:
        win.show()
    return app.exec()


def _set_app_user_model_id() -> None:
    """设置 AppUserModelID，让任务栏正确归组并使用 exe 图标。"""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"{APP_NAME}.App.1")
    except Exception:  # noqa: BLE001
        pass
