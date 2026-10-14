"""GUI 冒烟测试：离屏构建主窗口与各页签，检查不崩溃。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from junkcleaner import gui

    app = QApplication([sys.argv[0]])
    app.setStyleSheet(gui.QSS)
    win = gui.MainWindow()
    win.show()
    app.processEvents()

    # 各页签切换一次
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        app.processEvents()
        print(f"tab {i}: {win.tabs.tabText(i)} OK")

    # 伪造一份扫描结果，验证表格渲染与详情渲染
    from junkcleaner import scanner
    fake = scanner.Finding(
        sig_id="360.weishi", name="360安全卫士", vendor="360（奇虎）", risk="rogue",
        tags=["捆绑", "弹窗"], why="测试用", selected=True,
        uninstall_entries=[{"display_name": "360安全卫士", "publisher": "Qihoo",
                            "version": "12", "install_location": "C:\\360safe"}],
        processes=[{"pid": 1, "name": "360tray.exe", "exe": "C:\\360safe\\360tray.exe"}],
        services=[{"name": "360safe", "display": "360", "state": "Running"}],
        tasks=["\\360\\update"], paths=["C:\\360safe"])
    win.all_findings = [fake.to_dict()]
    win._apply_filter()
    app.processEvents()
    rows = win.table.rowCount()
    print(f"table rows: {rows}")
    assert rows == 1, "表格渲染失败"
    win.table.selectRow(0)
    app.processEvents()
    html = win.detail.toHtml()
    assert "360安全卫士" in html, "详情渲染失败"
    print("detail render OK")

    # 可信软件页：确认页面存在且能渲染
    trust_tab = [i for i in range(win.tabs.count())
                 if win.tabs.tabText(i) == "可信软件"]
    assert trust_tab, "缺少可信软件页"
    win.tabs.setCurrentIndex(trust_tab[0])
    app.processEvents()
    assert win.trust_page.tabs.count() == 3, "可信软件子页异常"
    print("trust page OK")
    # 必须真正跑一段事件循环再退出：后台 QThread 需要在事件循环里
    # 完成收尾，否则解释器退出时进程会随机以 0xc0000409 结束。
    # 真实用户路径由 run_gui 的 aboutToQuit -> _stop_all_workers 兜底。
    from PySide6.QtCore import QTimer
    QTimer.singleShot(300, win.close)
    QTimer.singleShot(600, app.quit)
    app.exec()
    gui._stop_all_workers(win)
    app.processEvents()
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
