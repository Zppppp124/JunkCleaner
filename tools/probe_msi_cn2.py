"""深挖 msi.cn Afterburner 页面里的真实下载入口。"""

from __future__ import annotations

import gzip
import re
import zlib
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
PAGE = "https://www.msi.cn/Landing/afterburner/graphics-cards"


def fetch(url: str, timeout: int = 30) -> bytes:
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
            pass
    return raw


def main() -> int:
    html = fetch(PAGE).decode("utf-8", "replace")
    print(f"页面长度: {len(html)}")
    print("=" * 74)

    # 所有 script 里的 url / api 端点
    print("[1] script / 数据端点")
    for m in sorted(set(re.findall(
            r'["\'](https?://[^"\']*(?:api|download|driver|norton|afterburner)'
            r'[^"\']*)["\']', html, re.I)))[:30]:
        print("   ", m)

    print("=" * 74)
    print("[2] 含 download / dl / get 的属性")
    for m in sorted(set(re.findall(
            r'(?:href|src|data-[a-z]+)\s*=\s*["\']([^"\']{4,200})["\']',
            html, re.I))):
        if re.search(r"download|/dl|norton|afterburner|setup", m, re.I):
            print("   ", m)

    print("=" * 74)
    print("[3] Norton downloadTemplateId 相关片段")
    for m in re.finditer(r"downloadTemplateId[^,;]{0,80}", html):
        print("   ", m.group(0))

    print("=" * 74)
    print("[4] 页面里出现的所有 _blank / target 链接")
    for m in sorted(set(re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*target="_blank"', html, re.I)))[:25]:
        print("   ", m)

    print("=" * 74)
    print("[5] 搜索 zip/exe/msi 关键词上下文")
    for m in re.finditer(r".{70}\.(zip|exe|msi).{20}", html, re.I):
        print("   ...", m.group(0).replace("\n", " ")[:140])

    print("=" * 74)
    print("[6] 尝试 Norton 端点")
    for tid in set(re.findall(r"downloadTemplateId=(\d+)", html)):
        url = f"https://dls2-int.norton.com/v1/downloads?downloadTemplateId={tid}"
        print(f"   {url}")
        try:
            raw = fetch(url)
            print(f"     -> {len(raw)} 字节: {raw[:160]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"     -> 失败 {str(exc)[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
