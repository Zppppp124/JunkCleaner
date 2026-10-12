"""验证 Afterburner 安装包校验：必须拒绝 Norton 推广包。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import afterburner as ab  # noqa: E402


def main() -> int:
    print("=" * 74)
    print("[1] 校验官方 Afterburner 安装器（必须通过）")
    official = Path(r"I:\CODEX\JunkCleaner\runtime\ab_check"
                    r"\MSIAfterburnerInstaller466_20260922.exe")
    if official.exists():
        r = ab.verify_installer(official)
        print(f"    结果: {r}")
        ok1 = bool(r.get("ok"))
        print(f"    通过: {'是' if ok1 else '否 <<< 问题'}")
    else:
        print("    文件不存在，跳过")
        ok1 = True

    print("=" * 74)
    print("[1b] 校验 Norton 推广包（必须拒绝）")
    norton = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner"
                  r"\MSIAfterburnerSetup.exe")
    if norton.exists():
        r = ab.verify_installer(norton)
        print(f"    结果: {r}")
        ok1b = not r.get("ok")
        print(f"    已拒绝: {'是' if ok1b else '否 <<< 严重问题'}")
    else:
        print("    文件不存在，跳过（此前已删除）")
        ok1b = True
    ok1 = ok1 and ok1b

    print("=" * 74)
    print("[2] 校验一个错误下载（HTML 页面，之前踩过的坑）")
    html = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner\_fake.html")
    html.write_bytes(b"<!DOCTYPE html><html><body>Not a zip</body></html>" * 40)
    r2 = ab.verify_installer(html)
    print(f"    结果: {r2}")
    ok2 = not r2.get("ok")
    print(f"    已拒绝: {'是' if ok2 else '否 <<< 问题'}")
    html.unlink(missing_ok=True)

    print("=" * 74)
    print("[3] 手工造一个含 Afterburner 特征的假 PE（应通过特征检查）")
    fake = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner\_fake_ab.exe")
    payload = bytearray(b"MZ" + b"\x00" * 4096)
    payload[512:512 + 12] = b"MSIAfterburner"
    fake.write_bytes(bytes(payload))
    r3 = ab.verify_installer(fake)
    print(f"    结果: {r3}")
    ok3 = r3.get("ok")
    print(f"    通过: {'是' if ok3 else '否'}")
    fake.unlink(missing_ok=True)

    print("=" * 74)
    print("[4] 当前是否已装 Afterburner")
    print(f"    installed={ab.is_installed()}  path={ab.find()}")
    print(f"    download_dir={ab.download_dir()}")

    print("=" * 74)
    allok = ok1 and ok2 and ok3
    print("RESULT:", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
