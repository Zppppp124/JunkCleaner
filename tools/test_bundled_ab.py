"""验证内嵌 Afterburner 安装包的识别与校验（不做实际安装）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import afterburner as ab  # noqa: E402


def main() -> int:
    print("=" * 74)
    print("[1] 内嵌安装包定位")
    b = ab.bundled_zip()
    print(f"    路径: {b}")
    if b is None:
        print("    未内嵌（标准版）")
        return 0
    print(f"    大小: {b.stat().st_size/1e6:.2f} MB")

    print("=" * 74)
    print("[2] 校验内嵌包")
    v = ab.verify_installer(b)
    print(f"    结果: {v}")

    print("=" * 74)
    print("[3] 解压后校验安装器")
    setup = ab.extract(b) if v.get("kind") == "zip" else b
    print(f"    安装器: {setup}")
    if setup:
        v2 = ab.verify_installer(setup)
        print(f"    结果: {v2}")
        info = ab._pe_version_info(setup)
        print(f"    产品名: {info.get('P')}")
        print(f"    公司名: {info.get('C')}")
        print(f"    版本  : {info.get('F')}")

    print("=" * 74)
    print("[4] 静默安装目标目录")
    print(f"    {ab.install_dir() / 'runtime' / 'MSI Afterburner'}")
    print(f"    NSIS /D= 支持: "
          f"{'是' if setup and b'/D=' in setup.read_bytes() else '未知'}")

    ok = bool(v.get("ok")) and bool(setup)
    print("=" * 74)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
