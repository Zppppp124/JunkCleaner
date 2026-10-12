#!/usr/bin/env python3
"""Gather public Chinese-web articles about junk / rogue software, for building
the built-in signature list. Network research helper only; not shipped logic."""

from __future__ import annotations

import html
import re
import sys
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

QUERIES = [
    "国产垃圾软件 排行榜 知乎",
    "流氓软件 名单 大全 卸载",
    "360安全卫士 腾讯电脑管家 流氓软件 争议",
    "电脑垃圾软件 排行 清理 推荐",
    "捆绑安装 流氓软件 黑名单",
    "微软电脑管家 争议 卸载",
    "2345 全家桶 流氓",
    "鲁大师 驱动人生 捆绑 流氓软件",
]


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"(?is)<(script|style).*?</\1>", " ", fragment)
    fragment = re.sub(r"(?s)<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()


def search(query: str) -> list[tuple[str, str, str]]:
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query) + "&count=30"
    page = fetch(url)
    out: list[tuple[str, str, str]] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        href, title = m.group(1), strip_tags(m.group(2))
        p = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = strip_tags(p.group(1)) if p else ""
        out.append((title, href, snippet))
    return out


def main() -> None:
    for q in QUERIES:
        print("=" * 78)
        print(f"QUERY: {q}")
        try:
            rows = search(q)
        except Exception as exc:  # noqa: BLE001 - research helper
            print(f"  [ERROR] {exc}")
            continue
        for title, href, snippet in rows[:8]:
            print(f"- {title}\n  {href}\n  {snippet[:300]}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
