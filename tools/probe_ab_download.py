"""探测 MSI Afterburner 官方下载地址与安装器类型（决定能否静默安装到指定目录）。"""

from __future__ import annotations

import struct
import sys
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

CANDIDATES = [
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip",
    "https://download.msi.com/uti_exe/gpu/MSIAfterburnerSetup.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup466.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup465.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup464.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup463.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip",
]


def head(url: str, timeout: int = 25) -> tuple[int, int, str]:
    # 用带 Range 的 GET 代替 HEAD（部分 CDN 拒绝 HEAD）
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Range": "bytes=0-1023",
                      "Referer": "https://www.msi.com/Landing/afterburner"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cr = r.headers.get("Content-Range") or ""
            total = 0
            if "/" in cr:
                try:
                    total = int(cr.split("/")[-1])
                except ValueError:
                    total = 0
            if not total:
                total = int(r.headers.get("Content-Length") or 0)
            return (r.status, total, r.headers.get("Content-Type") or "")
    except Exception as exc:  # noqa: BLE001
        return (0, 0, str(exc)[:90])


def main() -> int:
    print("=" * 74)
    print("探测 MSI Afterburner 官方下载地址")
    print("=" * 74)
    ok_url = ""
    for u in CANDIDATES:
        st, ln, ct = head(u)
        mark = "OK " if st == 200 else "-- "
        print(f"  {mark} {st:>3}  {ln/1e6:6.1f} MB  {u}")
        if st == 200 and not ok_url:
            ok_url = u
        if st != 200:
            print(f"         {ct}")

    if not ok_url:
        print("\n没有可用的下载地址（可能需要登录或链接已变）")
        return 1

    print("=" * 74)
    print(f"下载并识别安装器：{ok_url}")
    out = Path(r"I:\CODEX\JunkCleaner\_DL_test")
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / "MSIAfterburnerSetup.zip"
    try:
        req = urllib.request.Request(ok_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r, \
                zpath.open("wb") as fh:
            total = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
        print(f"  已下载 {total/1e6:.1f} MB -> {zpath}")
    except Exception as exc:  # noqa: BLE001
        print(f"  下载失败: {exc}")
        return 1

    # 解压看内容
    import zipfile
    try:
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            print(f"  压缩包内含 {len(names)} 个文件:")
            for n in names[:20]:
                info = z.getinfo(n)
                print(f"    {info.file_size/1e6:7.2f} MB  {n}")
            exe_name = next((n for n in names if n.lower().endswith(".exe")), "")
            if exe_name:
                data = z.read(exe_name)
                print(f"\n  安装器: {exe_name}  ({len(data)/1e6:.1f} MB)")
                # 检测安装器类型（NSIS / Inno / InstallShield）
                markers = {
                    "NSIS": b"Nullsoft",
                    "NSIS2": b"NSIS",
                    "Inno Setup": b"Inno Setup",
                    "InstallShield": b"InstallShield",
                    "MSI": b"msiexec",
                }
                for name, sig in markers.items():
                    if sig in data:
                        print(f"    -> 检测到 {name} 标记")
                # 找 /S /VERYSILENT 等提示串
                for flag in (b"/S", b"/VERYSILENT", b"/SUPPRESSMSGBOXES",
                             b"/D=", b"/SILENT", b"/qn"):
                    if flag in data:
                        print(f"    -> 含命令行开关 {flag.decode()}")
                # 保存安装器供后续测试
                target = out / exe_name
                target.write_bytes(data)
                print(f"    已保存安装器到 {target}")
    except Exception as exc:  # noqa: BLE001
        print(f"  解压失败: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
