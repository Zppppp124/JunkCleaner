"""集成测试：GUI 启动拦截按钮 + 开机自启计划任务。"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import core, guard  # noqa: E402


def test_guard_button() -> bool:
    from PySide6.QtWidgets import QApplication
    from junkcleaner import gui

    tmp = Path(tempfile.mkdtemp(prefix="jc_gui_guard_"))
    guard.WATCH_DIRS.insert(0, str(tmp))
    app = QApplication.instance() or QApplication([sys.argv[0]])
    win = gui.MainWindow()
    win.tabs.setCurrentIndex(1)
    win.toggle_guard()          # 等价于点击「启动拦截」
    app.processEvents()
    started = bool(win.guard_watcher and win.guard_watcher.running)
    print(f"启动拦截按钮 -> 守护运行: {started}")
    print(f"按钮文字: {win.btn_guard.text()}  状态: {win.stat_state.text()}")

    risky = tmp / "捆绑安装器_极速下载.exe"
    risky.write_bytes(b"MZ")
    blocked = False
    for _ in range(12):          # 轮询间隔 1s，最多等 6s
        time.sleep(0.5)
        app.processEvents()
        if not risky.exists():
            blocked = True
            break
    print(f"投放安装包被拦截: {blocked}")
    win.guard_watcher.stop()
    win._quit_app()
    for f in (core.quarantine_dir() / "installers").glob("*极速下载*"):
        f.unlink(missing_ok=True)
    return started and blocked


def test_autostart_task() -> bool:
    ok, out = guard.install_autostart()
    installed = guard.autostart_installed()
    print(f"注册自启任务: ok={ok} installed={installed}")
    removed_ok, _ = guard.remove_autostart()
    still = guard.autostart_installed()
    print(f"移除自启任务: removed={removed_ok} 仍存在={still}")
    return ok and installed and not still


def main() -> int:
    print("== 测试 1: GUI 启动拦截 ==")
    r1 = test_guard_button()
    print("\n== 测试 2: 开机自启计划任务 ==")
    r2 = test_autostart_task()
    print("\nRESULT:", "PASS" if (r1 and r2) else f"FAIL (guard={r1}, autostart={r2})")
    return 0 if (r1 and r2) else 1


if __name__ == "__main__":
    raise SystemExit(main())
