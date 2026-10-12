"""验证 Afterburner 安装器的数字签名，并检查 Norton 字符串的上下文。"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

ZIP = Path(r"I:\下载\MSIAfterburnerSetup.zip")
OUT = Path(r"I:\CODEX\JunkCleaner\runtime\ab_check")


def ps(script: str) -> str:
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
        capture_output=True)
    return ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP) as z:
        name = z.namelist()[0]
        exe = OUT / name
        exe.write_bytes(z.read(name))
    print(f"安装器: {exe}  {exe.stat().st_size/1e6:.2f} MB")
    print("=" * 74)
    print("[1] 数字签名验证")
    print(ps(f"$s=Get-AuthenticodeSignature -LiteralPath '{exe}';"
             "'Status : ' + $s.Status;"
             "'Signer : ' + $s.SignerCertificate.Subject;"
             "'Issuer : ' + $s.SignerCertificate.Issuer;"
             "'Thumbprint: ' + $s.SignerCertificate.Thumbprint;"
             "'Valid  : ' + $s.SignerCertificate.NotAfter"))

    print("=" * 74)
    print("[2] 文件版本信息")
    print(ps(f"(Get-Item '{exe}').VersionInfo | "
             "Select-Object FileVersion,ProductVersion,ProductName,"
             "CompanyName,FileDescription,LegalCopyright | Format-List | Out-String"))

    print("=" * 74)
    print("[3] Norton 字符串的上下文（判断是推广项还是真捆绑）")
    data = exe.read_bytes()
    for m in list(re.finditer(rb"Norton", data))[:6]:
        start = max(0, m.start() - 60)
        seg = data[start:m.start() + 80]
        txt = re.sub(rb"[^\x20-\x7e]", b".", seg).decode("ascii", "replace")
        print(f"   @{m.start():#x}  {txt}")

    print("=" * 74)
    print("[4] Afterburner 版本与关键组件")
    for kw in (b"RTCore64", b"MSIAfterburner.exe", b"RivaTuner",
               b"4.6.6", b"Afterburner"):
        print(f"   {'有' if kw in data else '无'}  {kw.decode()}")

    print("=" * 74)
    print("[5] NSIS 静默开关支持")
    for flag in (b"/S", b"/D=", b"/NCRC"):
        print(f"   {'有' if flag in data else '无'}  {flag.decode()}")

    print("=" * 74)
    print("[6] 官方安装器的默认安装路径提示")
    for m in list(re.finditer(rb"Program Files[^\x00]{0,60}", data))[:5]:
        print("   ", m.group(0).decode("ascii", "replace")[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
