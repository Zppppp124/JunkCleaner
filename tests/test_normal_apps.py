"""正常软件（WPS/搜狗）行为测试：本体放行，第三方捆绑照拦。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import core, guard, scanner, signatures  # noqa: E402


def wait_for(predicate, timeout: float = 8.0, step: float = 0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def main() -> int:
    failures: list[str] = []

    # 1) 本体识别
    positives = ["wps.exe", "WPS.EXE", "sogouimebroker.exe", "SGTool.exe", "et.exe"]
    negatives = ["chrome.exe", "360tray.exe", "installer.exe"]
    for name in positives:
        if not guard.is_known_normal_exe(name):
            failures.append(f"未识别为正常软件: {name}")
    for name in negatives:
        if guard.is_known_normal_exe(name):
            failures.append(f"误判为正常软件: {name}")
    print(f"本体识别: 正向 {len(positives)} 反向 {len(negatives)} 检查完成")

    # 2) 签名档位：WPS / 搜狗应为 normal
    wps = signatures.by_id("kingsoft.wps")
    sogou = signatures.by_id("sogou.input")
    for sig, label in ((wps, "WPS"), (sogou, "搜狗输入法")):
        if sig["risk"] != "normal" or not sig.get("silent_allow"):
            failures.append(f"{label} 档位异常: {sig['risk']}")
    print(f"档位: WPS={wps['risk']} 搜狗={sogou['risk']}（应为 normal）")

    # 3) 扫描结果中正常软件标记为 trusted / known_normal
    found = scanner.scan(include_disputed=True, compute_size=False)
    normal_rows = [f for f in found if f.risk == "normal"]
    for f in normal_rows:
        if not (f.trusted and f.known_normal and not f.selected):
            failures.append(f"{f.name} 未标记为正常放行")
    print(f"扫描中正常软件: {[(f.name, f.trusted, f.selected) for f in normal_rows]}")

    # 4) 实时防护：WPS 安装包放行，第三方安装器拦截
    workdir = Path(tempfile.mkdtemp(prefix="jc_normal_"))
    guard.WATCH_DIRS.insert(0, str(workdir))
    watcher = guard.InstallerWatcher(notify=lambda *_: None, interval=1.0)
    watcher.start()
    time.sleep(1.5)

    wps_setup = workdir / "WPS_Setup_2026.exe"
    wps_setup.write_bytes(b"MZ wps")
    time.sleep(2.5)
    wps_kept = wps_setup.exists()

    third_party = workdir / "极速下载器_安装管家.exe"
    third_party.write_bytes(b"MZ bundle")
    blocked = wait_for(lambda: not third_party.exists(), timeout=8)

    watcher.stop()
    print(f"WPS 安装包放行: {wps_kept}")
    print(f"第三方捆绑安装器拦截: {blocked}")
    if not wps_kept:
        failures.append("WPS 安装包被误拦")
    if not blocked:
        failures.append("第三方安装器未被拦截")

    # 清理
    for f in (wps_setup, third_party):
        f.unlink(missing_ok=True)
    for q in (core.quarantine_dir() / "installers").glob("*极速下载器*"):
        q.unlink(missing_ok=True)
    try:
        workdir.rmdir()
    except OSError:
        pass

    print()
    if failures:
        for f in failures:
            print("  FAIL:", f)
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
