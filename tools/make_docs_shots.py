"""生成说明书用的界面截图（隔离数据目录，不影响正在运行的实例）。

用法：
    python tools\\make_docs_shots.py

会在 docs\\images\\ 下生成各页签的截图。采用离屏渲染 + 显式加载
中文字体（微软雅黑），避免出现方块字。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "docs" / "images"
DATA = Path(os.environ.get("TEMP", r"C:\Windows\Temp")) / "jc_docs_data"

TABS = {
    "scan": 0, "guard": 1, "trust": 2, "memory": 3,
    "defender": 4, "gpu": 5, "hardware": 6, "quarantine": 7, "logs": 8,
}

def seed_data() -> None:
    """写入一份示例扫描结果，让截图内容更贴近真实使用。"""
    DATA.mkdir(parents=True, exist_ok=True)
    # 明确关闭实时防护，确保截图实例不会去动真实的下载/桌面文件
    (DATA / "config.json").write_text(json.dumps({
        "guard_enabled": False,
        "auto_quarantine_installer": False,
        "scan_intensity": "low",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "status.json").write_text(json.dumps(
        {"guard_running": False}, ensure_ascii=False), encoding="utf-8")
    findings = [
        {
            "sig_id": "360.weishi", "name": "360安全卫士", "vendor": "360（奇虎）",
            "risk": "rogue", "tags": ["捆绑", "弹窗", "主页劫持"],
            "why": "安装包捆绑第三方软件，且难以彻底卸载",
            "selected": True,
            "uninstall_entries": [{"display_name": "360安全卫士", "publisher": "Qihoo 360",
                                   "version": "13.0.0.2005",
                                   "install_location": r"C:\Program Files (x86)\360\360Safe"}],
            "processes": [{"pid": 4321, "name": "360tray.exe",
                           "exe": r"C:\Program Files (x86)\360\360Safe\360tray.exe"}],
            "services": [{"name": "360Safe", "display": "360安全卫士", "state": "Running"}],
            "tasks": [r"\360\360Update"],
            "paths": [r"C:\Program Files (x86)\360\360Safe"],
            "startup": ["360tray.exe"], "computed_size": 268435456,
            "last_activity": "2026-10-12 20:15:02",
        },
        {
            "sig_id": "2345.explorer", "name": "2345加速浏览器", "vendor": "2345.com",
            "risk": "bundle", "tags": ["捆绑", "静默安装"],
            "why": "以推广捆绑方式安装，默认设置主页",
            "selected": True,
            "uninstall_entries": [{"display_name": "2345加速浏览器", "publisher": "2345.com",
                                   "version": "10.5", "install_location": r"C:\2345Explorer"}],
            "processes": [], "services": [], "tasks": [r"\2345Explorer\Update"],
            "paths": [r"C:\2345Explorer"], "startup": [],
            "computed_size": 134217728, "last_activity": "2026-10-12 19:40:11",
        },
        {
            "sig_id": "wps.bundle", "name": "WPS Office 捆绑安装器", "vendor": "金山办公",
            "risk": "bundle", "tags": ["父子进程拦截"],
            "why": "WPS 子进程拉起第三方下载器",
            "selected": False,
            "uninstall_entries": [], "processes": [],
            "services": [], "tasks": [], "paths": [], "startup": [],
            "computed_size": 0, "last_activity": "",
        },
    ]
    (DATA / "last_scan.json").write_text(json.dumps(
        {"time": "2026-10-12 21:20:00", "count": len(findings),
         "findings": findings}, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
        {"time": "2026-10-12 21:18:42", "kind": "block_installer",
         "title": "已隔离捆绑安装器", "detail": r"E:\下载\极速下载器_setup.exe"},
        {"time": "2026-10-12 21:12:07", "kind": "block_process",
         "title": "已拦截可疑子进程", "detail": "WPS.exe -> softmgr.exe"},
    ]) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    seed_data()
    os.environ["JUNKCLEANER_DATA"] = str(DATA)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase

    sys.path.insert(0, str(BASE))
    from junkcleaner import gui

    app = QApplication.instance() or QApplication(sys.argv[:1])
    # 显式加载中文字体，否则离屏渲染会出现方块字
    for font in ("msyh.ttc", "simhei.ttf", "ARIALUNI.TTF"):
        path = Path(r"C:\Windows\Fonts") / font
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setStyleSheet(gui.QSS)

    win = gui.MainWindow()
    win.resize(1180, 800)
    win.show()
    app.processEvents()
    done = 0
    for name, tab in TABS.items():
        win.tabs.setCurrentIndex(tab)
        app.processEvents()
        if hasattr(win, "tuning_page") and tab == TABS["gpu"]:
            win.tuning_page._refresh_gpu()
            win.tuning_page._refresh_live()
            app.processEvents()
        out = OUT / f"{name}.png"
        if win.grab().save(str(out)):
            done += 1
            print(f"{name}: OK -> {out.name}")
        else:
            print(f"{name}: FAIL")
    win.close()
    print(f"完成 {done}/{len(TABS)}，输出目录 {OUT}")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
