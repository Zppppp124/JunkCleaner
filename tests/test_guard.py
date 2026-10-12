"""实时防护测试：内核事件拦截 + 可信白名单放行。"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import core, guard, trust  # noqa: E402


def wait_for(predicate, timeout: float = 8.0, step: float = 0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="jc_rt_"))
    guard.WATCH_DIRS.insert(0, str(workdir))
    caught: list[tuple[str, str]] = []
    watcher = guard.InstallerWatcher(notify=lambda t, m: caught.append((t, m)),
                                     interval=1.0)
    watcher.start()
    time.sleep(1.5)

    risky = workdir / "高速下载器_setup_20260101.exe"
    risky.write_bytes(b"MZ fake")
    blocked = wait_for(lambda: not risky.exists(), timeout=8)
    quarantined = list((core.quarantine_dir() / "installers").glob("*高速下载器*"))

    trusted_dir = workdir / "TrustedApp"
    trusted_dir.mkdir()
    entry = trust.add_trust("测试可信软件", "path", str(trusted_dir), source="test")
    safe = trusted_dir / "高速下载器_setup_20260101.exe"
    safe.write_bytes(b"MZ trusted")
    time.sleep(3.0)
    safe_kept = safe.exists()

    normal = workdir / "mytool.exe"
    normal.write_bytes(b"MZ normal")
    time.sleep(2.0)
    normal_kept = normal.exists()

    watcher.stop()
    trust.remove_trust(entry["id"])

    print(f"模式: {watcher.stats['mode']}  捕获事件: {watcher.stats['events']}")
    print(f"可疑安装包被隔离: {blocked} -> {[q.name for q in quarantined]}")
    print(f"白名单软件被放行: {safe_kept}")
    print(f"普通文件未被误伤: {normal_kept}")
    print(f"通知: {caught}")

    ok = blocked and bool(quarantined) and safe_kept and normal_kept
    for q in quarantined:
        q.unlink(missing_ok=True)
    for f in (safe, normal):
        f.unlink(missing_ok=True)
    try:
        trusted_dir.rmdir()
        workdir.rmdir()
    except OSError:
        pass
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
