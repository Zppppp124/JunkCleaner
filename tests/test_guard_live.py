"""实景验证：在真实下载目录投放可疑安装包，确认被实时拦截并隔离。"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import core, guard  # noqa: E402


def main() -> int:
    downloads = Path(os.path.expandvars(r"%USERPROFILE%\Downloads"))
    downloads.mkdir(parents=True, exist_ok=True)
    sample = downloads / f"360安全卫士_官方下载_极速安装器_{int(time.time())}.exe"
    watcher = guard.InstallerWatcher(
        notify=lambda t, m: print(f"  [通知] {t}: {m.splitlines()[0]}"),
        interval=1.0)
    watcher.start()
    time.sleep(1.5)                      # 先让守护完成初始快照
    sample.write_bytes(b"MZ" + b"\x00" * 512)
    print(f"投放样本: {sample}")

    gone = False
    for _ in range(80):                       # 最多 8 秒
        time.sleep(0.1)
        if not sample.exists():
            gone = True
            break
    watcher.stop()

    quarantined = list((core.quarantine_dir() / "installers").glob(
        f"*{sample.stem}*"))
    print(f"样本被移出下载目录: {gone}")
    print(f"隔离区文件: {[q.name for q in quarantined]}")
    events = [e for e in core.read_events(20)
              if e.get("kind") == "block_installer"
              and sample.stem in str(e.get("file", ""))]
    print(f"事件记录: {len(events)} -> {events[:1]}")

    ok = gone and bool(quarantined) and bool(events)
    for q in quarantined:
        q.unlink(missing_ok=True)
    sample.unlink(missing_ok=True)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
