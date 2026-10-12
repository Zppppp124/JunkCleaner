"""从 MSI 中国站（msi.cn）查找 Afterburner 下载地址。"""

from __future__ import annotations

import gzip
import io
import re
import sys
import zlib
from pathlib import Path
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

PAGES = [
    "https://www.msi.cn/Landing/afterburner/graphics-cards",
    "https://www.msi.cn/Landing/afterburner",
    "https://www.msi.cn/page/afterburner",
    "https://cn.msi.com/Landing/afterburner/graphics-cards",
    "https://www.msi.cn/",
]


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if "gzip" in enc:
            try:
                raw = gzip.decompress(raw)
            except Exception:  # noqa: BLE001
                pass
        elif "deflate" in enc:
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:  # noqa: BLE001
                try:
                    raw = zlib.decompress(raw)
                except Exception:  # noqa: BLE001
                    pass
        return r.status, raw, r.geturl()


def decode(raw: bytes) -> str:
    for e in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(e)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main() -> int:
    # 先看看上一次自动下载下来的是什么
    prev = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner"
                r"\MSIAfterburnerSetup.zip")
    if prev.exists():
        data = prev.read_bytes()
        print("=" * 74)
        print(f"上次下载的文件: {prev}")
        print(f"  大小: {len(data)} 字节")
        head = data[:400]
        if head[:2] == b"PK":
            print("  -> 是有效的 ZIP")
        else:
            txt = decode(head)
            print("  -> 不是 ZIP，前 200 字符:")
            print("     " + txt[:200].replace("\n", " "))

    found: set[str] = set()
    for page in PAGES:
        print("=" * 74)
        print(f"页面: {page}")
        try:
            st, raw, final = fetch(page)
        except Exception as exc:  # noqa: BLE001
            print(f"  失败: {str(exc)[:120]}")
            continue
        print(f"  状态 {st}  最终地址 {final}  长度 {len(raw)}")
        html = decode(raw)
        for pat in (
                r'https?://[^"\'\s<>]+\.(?:zip|exe|msi)',
                r'["\'](//[^"\'\s<>]+\.(?:zip|exe|msi))["\']',
                r'["\'](/[^"\'\s<>]*(?:[Dd]ownload|afterburner)[^"\'\s<>]*)["\']',
        ):
            for m in re.findall(pat, html):
                if m.startswith("//"):
                    found.add("https:" + m)
                elif m.startswith("/"):
                    found.add("https://www.msi.cn" + m)
                else:
                    found.add(m)
        # 版本号
        for v in re.findall(r"[Aa]fterburner[^<>\n]{0,60}?(\d\.\d\.\d)", html):
            print(f"  版本提示: {v}")
        # 任何含 download 的链接
        for m in re.findall(r'href="([^"]*[Dd]ownload[^"]*)"', html)[:10]:
            print(f"  链接: {m}")

    print("=" * 74)
    print(f"发现 {len(found)} 个候选:")
    for u in sorted(found):
        print("  ", u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
