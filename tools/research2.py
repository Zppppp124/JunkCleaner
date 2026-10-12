#!/usr/bin/env python3
"""Bing-based research for junk/rogue software names."""

from __future__ import annotations

import html
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

QUERIES = [
    '"流氓软件" 名单 360 2345 电脑管家 卸载',
    '"全家桶" 软件 卸载 电脑 2345 360',
    '电脑 垃圾软件 排行 十大 卸载',
    '流氓软件 排行 知乎 捆绑 弹窗',
    '微软电脑管家 卸载 争议',
    '鲁大师 驱动人生 捆绑 弹窗 卸载',
    '软件下载站 捆绑 流氓 名单 高速下载器',
    '国家网信办 捆绑 弹窗 软件 名单 整治',
    '国产 安全软件 流氓 行为 排行',
    'flash helper 流氓软件 卸载',
]


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?s)<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def bing(query: str) -> None:
    url = ("https://cn.bing.com/search?q=" + urllib.parse.quote(query)
           + "&count=30&setlang=zh-CN")
    try:
        page = fetch(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERROR] {exc}")
        return
    blocks = re.findall(r'<li class="b_algo".*?</li>', page, re.S)
    for block in blocks[:10]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snip = strip_tags(p.group(1)) if p else ""
        print(f"- {strip_tags(m.group(2))}\n  {html.unescape(m.group(1))}\n  {snip[:500]}")


def main() -> None:
    for q in QUERIES:
        print("=" * 78)
        print(f"QUERY: {q}")
        bing(q)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
