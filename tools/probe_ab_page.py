"""从 MSI 官方网站页面抓取真实的 Afterburner 下载链接。"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.msi.com/",
    "Connection": "keep-alive",
}

PAGES = [
    "https://www.msi.com/Landing/afterburner/graphics-cards",
    "https://www.msi.com/Landing/afterburner",
    "https://www.msi.com/page/afterburner",
]


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main() -> int:
    found: set[str] = set()
    for page in PAGES:
        print("=" * 74)
        print(f"页面: {page}")
        try:
            html = fetch(page)
        except Exception as exc:  # noqa: BLE001
            print(f"  抓取失败: {str(exc)[:100]}")
            continue
        print(f"  长度 {len(html)}")
        for m in re.findall(
                r'https?://[^"\'\s<>]+\.(?:zip|exe|msi)', html, re.I):
            found.add(m)
        for m in re.findall(
                r'["\'](/[^"\'\s<>]*(?:download|Download)[^"\'\s<>]*)["\']',
                html):
            found.add("https://www.msi.com" + m)
        # 找版本号
        for m in re.findall(r"[Aa]fterburner[^<>\n]{0,40}?(\d\.\d\.\d)", html):
            print(f"  版本提示: {m}")

    print("=" * 74)
    print(f"共发现 {len(found)} 个候选链接:")
    for u in sorted(found):
        print("  ", u)
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
