"""验证用户提供的 Afterburner 安装包，并测试 token 链接。"""

from __future__ import annotations

import hashlib
import re
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import afterburner as ab  # noqa: E402

TOKEN_URL = (
    "https://download-2.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip"
    "?__token__=exp=1791961532~acl=/*"
    "~hmac=a494e1b72a24e2217d270a22dfd141d03ddd1e4cef1f7ee405d79899bc23a1e4"
)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def main() -> int:
    # 0) token 里的过期时间
    m = re.search(r"exp=(\d+)", TOKEN_URL)
    if m:
        exp = int(m.group(1))
        print(f"token exp = {exp}  ->  "
              f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(exp))}")
        print(f"  现在时间 = {time.strftime('%Y-%m-%d %H:%M:%S')}  "
              f"{'已过期' if time.time() > exp else '仍有效'}")

    # 1) 找用户放的 zip
    cands = [
        Path(r"I:\下载\MSIAfterburnerSetup.zip"),
        Path(r"I:\下载\MSIAfterburnerSetup.zip".replace("MSIAfterburnerSetup",
                                                        "MSIAfterburnerSetup")),
    ]
    dl = Path(r"I:\下载")
    if dl.exists():
        for p in dl.glob("*fterburner*"):
            cands.append(p)
    # 去重
    seen: set[str] = set()
    uniq = []
    for c in cands:
        k = str(c).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(c)

    print("=" * 74)
    print("[1] 检查 I:\\下载 里的安装包")
    found: Path | None = None
    for c in uniq:
        if not c.exists():
            print(f"   不存在: {c}")
            continue
        size = c.stat().st_size
        print(f"   找到: {c}   {size/1e6:.2f} MB")
        head = c.read_bytes()[:4]
        print(f"   文件头: {head!r}  {'ZIP' if head[:2]==b'PK' else '非 ZIP'}")
        if head[:2] == b"PK":
            found = c
            break

    if found:
        print("=" * 74)
        print("[2] 解压并校验内容")
        try:
            with zipfile.ZipFile(found) as z:
                names = z.namelist()
                print(f"   内含 {len(names)} 个条目:")
                for n in names[:15]:
                    print(f"     {z.getinfo(n).file_size/1e6:7.2f} MB  {n}")
                exe = next((n for n in names
                            if n.lower().endswith(".exe")), "")
                print(f"   安装器: {exe}")
                if exe:
                    data = z.read(exe)
                    print(f"   大小: {len(data)/1e6:.2f} MB")
                    print(f"   SHA256: {hashlib.sha256(data).hexdigest()}")
                    markers = {
                        "NSIS": b"Nullsoft",
                        "含 Afterburner": b"Afterburner",
                        "含 RTCore": b"RTCore",
                        "Norton 推广": b"Norton",
                    }
                    for k, v in markers.items():
                        print(f"   {'有' if v in data else '无'}  {k}")
                    # 用我们的校验器判一次
                    out = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner")
                    out.mkdir(parents=True, exist_ok=True)
                    t = out / Path(exe).name
                    t.write_bytes(data)
                    r = ab.verify_installer(t)
                    print(f"   校验结果: {r}")
        except Exception as exc:  # noqa: BLE001
            print(f"   失败: {exc}")

    print("=" * 74)
    print("[3] 测试 token 链接是否可直接下载")
    try:
        req = Request(TOKEN_URL, headers={
            "User-Agent": UA, "Accept": "*/*",
            "Referer": "https://www.msi.com/Landing/afterburner/graphics-cards",
        })
        with urlopen(req, timeout=30) as r:
            head = r.read(64)
            print(f"   状态 {r.status}  Content-Type {r.headers.get('Content-Type')}")
            print(f"   前 16 字节: {head[:16]!r}")
            print(f"   -> {'是 ZIP（PK）' if head[:2]==b'PK' else '不是 ZIP'}")
    except Exception as exc:  # noqa: BLE001
        print(f"   失败: {str(exc)[:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
