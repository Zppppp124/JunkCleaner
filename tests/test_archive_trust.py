"""压缩包白名单测试：包内文件按指纹加入白名单后，解压到别处不被拦截。"""

from __future__ import annotations

import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import archive, core, guard, trust  # noqa: E402


def main() -> int:
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="jc_arc_"))
    payload = b"MZ" + b"trusted-payload" * 200

    # 造一个压缩包，里面放一个「名字本身会被启发式拦截」的可执行文件
    zp = tmp / "bundle.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("极速下载器_安装管家.exe", payload)

    entries = archive.list_entries(zp)
    print(f"压缩包条目: {[(e.name, e.size, e.is_executable) for e in entries]}")
    if not entries:
        failures.append("无法列出压缩包内容")

    digest = archive.read_member_hash(zp, entries[0].name)
    print(f"包内指纹: {digest[:16]}…")
    if not digest:
        failures.append("无法计算包内成员指纹")

    entry = trust.add_trust("测试包内文件", "hash", digest, source="test")

    # 模拟「解压到别处」：内容相同但路径完全不同
    extract_dir = Path(tempfile.mkdtemp(prefix="jc_extract_"))
    dropped = extract_dir / "totally_different_name.exe"
    dropped.write_bytes(payload)

    watcher = guard.InstallerWatcher(notify=lambda *_: None, interval=1.0)
    watcher.start()
    time.sleep(1.5)
    dropped.write_bytes(payload)          # 重新写入，触发文件监控
    time.sleep(3.0)
    survived = dropped.exists()
    watcher.stop()

    print(f"解压到别处后是否存活: {survived}")
    if not survived:
        failures.append("按指纹加入白名单的文件仍被拦截")

    # 指纹匹配本身
    if not trust.matches(exe_path=str(dropped),
                         file_hash=trust.sha256_cached(dropped, fallback=True)):
        failures.append("指纹匹配未命中")

    # 清理
    trust.remove_trust(entry["id"])
    for q in (core.quarantine_dir() / "installers").glob("*totally_different*"):
        q.unlink(missing_ok=True)
    for f in (dropped,):
        f.unlink(missing_ok=True)
    try:
        extract_dir.rmdir()
        zp.unlink(missing_ok=True)
        tmp.rmdir()
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
