"""从 Norton Download Manager 里提取真实下载链接。"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\runtime\afterburner\MSIAfterburnerSetup.exe")
    if not exe.exists():
        print("文件不存在")
        return 1
    data = exe.read_bytes()
    print(f"文件: {exe}  {len(data)/1e6:.2f} MB")
    print("=" * 74)

    # 提取可打印字符串
    strings = re.findall(rb"[\x20-\x7e]{8,200}", data)
    text = [s.decode("ascii", "replace") for s in strings]

    print("[1] 含 afterburner / msi.com 的字符串")
    seen = set()
    for s in text:
        low = s.lower()
        if ("afterburner" in low or "download.msi" in low
                or "storage-asset" in low) and s not in seen:
            seen.add(s)
            print("   ", s[:190])

    print("=" * 74)
    print("[2] 所有 http(s) URL")
    urls = set()
    for s in text:
        for m in re.findall(r"https?://[^\s\"'<>]{6,200}", s):
            urls.add(m)
    for u in sorted(urls)[:40]:
        print("   ", u)

    print("=" * 74)
    print("[3] 含 .exe / .zip / setup 的字符串")
    for s in sorted(set(text)):
        if re.search(r"\.(exe|zip|msi)\b", s, re.I) and len(s) < 200:
            print("   ", s[:190])

    print("=" * 74)
    print("[4] 命令行开关")
    for s in sorted(set(text)):
        if re.match(r"^/[A-Za-z]{1,20}(=.*)?$", s):
            print("   ", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
