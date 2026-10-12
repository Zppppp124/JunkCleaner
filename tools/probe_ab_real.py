"""寻找真正的 Afterburner 官方下载直链（排除 Norton 推广）。"""

from __future__ import annotations

import gzip
import re
import zlib
from pathlib import Path
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
H = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
}

PAGES = [
    # Guru3D 是 Afterburner 的官方合作分发方
    "https://www.guru3d.com/download/msi-afterburner-beta-download/",
    "https://www.guru3d.com/files-details/msi-afterburner-beta-download.html",
    # MSI 全球站（非中国推广页）
    "https://www.msi.com/Landing/afterburner/graphics-cards",
    "https://www.msi.com/page/afterburner",
    # 常见镜像
    "https://www.techpowerup.com/download/msi-afterburner/",
]


def fetch(url: str, timeout: int = 25) -> tuple[int, bytes, str]:
    req = Request(url, headers=H)
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        final = r.geturl()
        st = r.status
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
    return st, raw, final


def main() -> int:
    hits: dict[str, str] = {}
    for page in PAGES:
        print("=" * 74)
        print(f"页面: {page}")
        try:
            st, raw, final = fetch(page)
            html = raw.decode("utf-8", "replace")
            print(f"  状态 {st}  长度 {len(raw)}  最终 {final}")
        except Exception as exc:  # noqa: BLE001
            print(f"  失败: {str(exc)[:110]}")
            continue

        # 找下载文件的直链
        pats = [
            r'https?://[^"\'\s<>]+MSIAfterburner[^"\'\s<>]*\.(?:zip|exe)',
            r'https?://[^"\'\s<>]*[Aa]fterburner[^"\'\s<>]*\.(?:zip|exe)',
            r'https?://[^"\'\s<>]+\.(?:zip|exe)',
            r'href="([^"]*(?:download|getfile|mirror)[^"]*)"',
        ]
        for p in pats:
            for m in re.findall(p, html, re.I):
                u = m if isinstance(m, str) else m[0]
                if u.startswith("//"):
                    u = "https:" + u
                elif u.startswith("/"):
                    root = re.match(r"(https?://[^/]+)", final)
                    u = (root.group(1) if root else "") + u
                if re.search(r"norton|pcmag|buy-download", u, re.I):
                    continue
                hits[u] = page
        # 版本号
        for v in re.findall(r"[Aa]fterburner[^<>\n]{0,50}?(\d\.\d\.\d)", html):
            print(f"  版本提示: {v}")

    print("=" * 74)
    print(f"非 Norton 候选（{len(hits)}）:")
    for u, src in sorted(hits.items()):
        print(f"  {u}\n      <- {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
