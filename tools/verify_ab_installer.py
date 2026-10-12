"""下载并验证 Norton 托管的 Afterburner 安装器。"""

from __future__ import annotations

import gzip
import re
import sys
import zlib
from pathlib import Path
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.msi.cn/Landing/afterburner/graphics-cards",
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-site", "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
PAGE = "https://www.msi.cn/Landing/afterburner/graphics-cards"


def fetch(url: str, timeout: int = 180) -> tuple[bytes, str]:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        ctype = r.headers.get("Content-Type") or ""
        final = r.geturl()
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
    return raw, f"{ctype} -> {final}"


def main() -> int:
    # 1) 从官方页面拿 templateId
    html = fetch(PAGE)[0].decode("utf-8", "replace")
    ids = sorted(set(re.findall(r"downloadTemplateId=(\d+)", html)))
    print(f"页面里的 downloadTemplateId: {ids}")
    if not ids:
        print("没找到下载 ID")
        return 1
    tid = ids[0]
    url = f"https://dls2-int.norton.com/v1/downloads?downloadTemplateId={tid}"
    print(f"下载地址: {url}")
    print("=" * 74)

    data, meta = fetch(url)
    print(f"返回: {len(data) / 1e6:.2f} MB   {meta}")
    print(f"文件头: {data[:2]!r}")
    if data[:2] != b"MZ":
        print("不是可执行文件")
        return 1

    out = Path(r"I:\CODEX\JunkCleaner\runtime\afterburner")
    out.mkdir(parents=True, exist_ok=True)
    exe = out / "MSIAfterburnerSetup.exe"
    exe.write_bytes(data)
    print(f"已保存: {exe}")

    # 2) 识别安装器类型与静默开关
    print("=" * 74)
    markers = {
        "NSIS": b"Nullsoft",
        "Inno Setup": b"Inno Setup",
        "InstallShield": b"InstallShield",
    }
    for name, sig in markers.items():
        if sig in data:
            print(f"安装器类型: {name}")
    for flag in (b"/S", b"/VERYSILENT", b"/SILENT", b"/qn", b"/D=",
                 b"/SUPPRESSMSGBOXES", b"/NORESTART"):
        if flag in data:
            print(f"  含开关 {flag.decode()}")

    # 3) 版本信息
    print("=" * 74)
    try:
        import subprocess
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{exe}').VersionInfo | "
             "Select-Object FileVersion,ProductName,CompanyName,FileDescription"
             " | Format-List | Out-String"],
            capture_output=True)
        print((r.stdout or b"").decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        print("版本读取失败:", exc)

    # 4) 文件名提示
    print("=" * 74)
    print("字符串里搜索版本号:")
    for m in sorted(set(re.findall(rb"4\.\d\.\d", data)))[:8]:
        print("   ", m.decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
