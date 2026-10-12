"""MSI Afterburner 的定位与自动安装。

为什么不在打包时内嵌
--------------------
MSI Afterburner 是微星的专有软件，其许可不允许随第三方程序再分发。
直接把它打进我们的安装包属于侵权行为。

我们怎么做
----------
1. 先自动发现已安装的 Afterburner（常见路径 / 注册表 / 运行进程 / 浅层搜索）。
2. 没找到时提供一键「下载并安装」：
   * 走 MSI 官方地址下载（download.msi.com）
   * 若被 CDN 防护拦截，用系统浏览器打开官方下载页让用户手动完成，
     装好后自动重新检测
   * 安装时优先静默安装到指定目录；不支持则弹出安装向导
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Callable

from . import core

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

DOWNLOAD_URLS = [
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup470.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup466.zip",
    "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup465.zip",
]
LANDING_PAGE = "https://www.msi.com/Landing/afterburner/graphics-cards"
LANDING_PAGE_CN = "https://cn.msi.com/Landing/afterburner/graphics-cards"
# MSI 官方页面的「下载」实为 Norton 推广，绝不自动安装
# 注意：不能简单搜 "Norton" —— 官方 Afterburner 安装器里也含
#       "NortonLifeLock License and Services Agreement" 条款文本。
#       必须用「产品名 / 公司名」判定，见 _pe_info()。
FORBIDDEN_PRODUCTS = [b"Norton Download Manager", b"Norton 360",
                      b"Norton Security", b"Norton AntiVirus"]
AB_PRODUCTS = [b"MSI Afterburner", b"MSIAfterburner", b"Afterburner"]


def _pe_version_info(path: Path) -> dict[str, str]:
    """读取 PE 的版本资源（ProductName / CompanyName 等）。

    比字符串搜索可靠得多：官方安装器的许可文本里也含 "Norton"，
    只有版本信息才能区分「真 Afterburner」和「Norton 推广包」。
    """
    import subprocess
    info: dict[str, str] = {}
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
             f"$i=(Get-Item -LiteralPath '{path}').VersionInfo;"
             "[pscustomobject]@{P=$i.ProductName;C=$i.CompanyName;"
             "D=$i.FileDescription;F=$i.FileVersion} | "
             "ConvertTo-Json -Compress"],
            capture_output=True, timeout=60)
        import json
        d = json.loads((p.stdout or b"").decode("utf-8", "replace") or "{}")
        info = {k: str(v or "") for k, v in d.items()}
    except Exception:  # noqa: BLE001
        pass
    return info

BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def install_dir() -> Path:
    """程序所在目录。"""
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def download_dir() -> Path:
    d = install_dir() / "runtime" / "afterburner"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find() -> Path | None:
    from . import vfcurve
    return vfcurve.find_afterburner()


def is_installed() -> bool:
    return find() is not None


def verify_installer(path: Path) -> dict[str, Any]:
    """校验一个文件是否为真正的 Afterburner 安装器。

    为什么要校验：MSI 中国站/官方页面的下载按钮实际指向 Norton 推广包，
    如果直接安装会把 Norton 360 装进用户电脑。这里做双重校验：
      1. 文件是 PE/ZIP（不是 HTML 错误页）
      2. 含 Afterburner 特征，且不含 Norton/Gen Digital 特征
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"ok": False, "reason": f"读取失败：{exc}"}
    if len(data) < 1024:
        return {"ok": False, "reason": "文件过小"}

    head = data[:2]
    is_zip = head == b"PK"
    is_pe = head == b"MZ"
    if not (is_zip or is_pe):
        text = data[:200].decode("utf-8", "replace").strip()
        return {"ok": False, "reason": f"不是安装包（可能是网页）：{text[:80]}"}

    # PE 文件：以版本信息为准（字符串搜索会被许可文本误导）
    if is_pe:
        info = _pe_version_info(path)
        product = (info.get("P") or "").strip()
        company = (info.get("C") or "").strip()
        blob = (product + " " + company + " " +
                (info.get("D") or "")).encode("utf-8", "replace")
        if any(m in blob for m in FORBIDDEN_PRODUCTS):
            return {"ok": False, "norton": True,
                    "reason": f"这是 Norton 推广包（{product or company}），"
                              "不是 MSI Afterburner"}
        is_ab = any(m in blob for m in AB_PRODUCTS)
        # 版本信息缺失时（少见）退回字符串特征
        if not product and not company:
            is_ab = (b"MSI Afterburner Installer" in data
                     or b"MSIAfterburner" in data)
        if not is_ab:
            return {"ok": False,
                    "reason": f"产品信息不是 Afterburner："
                              f"{product or company or '（无版本信息）'}"}
        return {"ok": True, "kind": "exe", "product": product,
                "company": company, "version": info.get("F", "")}
    if is_zip:
        # zip 需解压后再验
        try:
            with zipfile.ZipFile(path) as z:
                names = " ".join(z.namelist())
            if "afterburner" not in names.lower():
                return {"ok": False,
                        "reason": "压缩包内未发现 Afterburner"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"压缩包损坏：{exc}"}
    return {"ok": True, "kind": "zip" if is_zip else "exe"}


def scan_manual_drop() -> dict[str, Any]:
    """检测用户手动放进 runtime\\afterburner 的安装包。"""
    d = download_dir()
    cands: list[Path] = []
    for pat in ("*.exe", "*.zip"):
        cands.extend(d.glob(pat))
    # 也看程序目录本身
    root = install_dir()
    for pat in ("MSIAfterburner*.exe", "MSIAfterburner*.zip"):
        cands.extend(root.glob(pat))
    for c in cands:
        r = verify_installer(c)
        if r.get("ok"):
            return {"ok": True, "file": str(c), "kind": r.get("kind")}
    return {"ok": False, "reason": "未发现可用的 Afterburner 安装包"}


def install_from_local(path: Path) -> dict[str, Any]:
    """用本地已有的安装包静默安装。"""
    v = verify_installer(path)
    if not v.get("ok"):
        return {"ok": False, "stage": "verify", "error": v.get("reason")}
    setup = path
    if v.get("kind") == "zip":
        setup = extract(path)
        if setup is None:
            return {"ok": False, "stage": "extract", "error": "解压失败"}
        v2 = verify_installer(setup)
        if not v2.get("ok"):
            return {"ok": False, "stage": "verify", "error": v2.get("reason")}
    return silent_install(setup)


def _try_download(url: str, dest: Path,
                  progress: Callable[[str], None] | None = None,
                  timeout: int = 300) -> tuple[bool, str]:
    import urllib.request
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = LANDING_PAGE
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            with dest.open("wb") as fh:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if progress and total:
                        progress(f"下载中 {got / 1e6:.1f}/{total / 1e6:.1f} MB")
        if dest.stat().st_size < 1024:
            return False, "下载内容过小，可能被拦截"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:160]


def download(progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    dest = download_dir() / "MSIAfterburnerSetup.zip"
    errors: list[str] = []
    for url in DOWNLOAD_URLS:
        if progress:
            progress(f"尝试 {url.rsplit('/', 1)[-1]}")
        ok, err = _try_download(url, dest, progress)
        if ok:
            # 关键：必须校验是真 Afterburner，不能是 Norton 推广包
            v = verify_installer(dest)
            if not v.get("ok"):
                errors.append(f"{url.rsplit('/', 1)[-1]}: {v.get('reason')}")
                core.log(f"下载内容校验未通过：{v.get('reason')}",
                         level="WARN", source="afterburner")
                dest.unlink(missing_ok=True)
                continue
            core.log(f"Afterburner 下载成功: {url}", source="afterburner")
            return {"ok": True, "path": str(dest), "url": url}
        errors.append(f"{url.rsplit('/', 1)[-1]}: {err}")
    core.log("Afterburner 自动下载失败: " + "; ".join(errors[:2]),
             level="WARN", source="afterburner")
    return {"ok": False, "errors": errors}


def open_official_page() -> bool:
    import webbrowser
    for url in (LANDING_PAGE_CN, LANDING_PAGE):
        try:
            webbrowser.open(url)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def extract(zip_path: Path) -> Path | None:
    try:
        out = zip_path.parent / "setup"
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out)
        for f in out.rglob("*.exe"):
            if "afterburner" in f.name.lower():
                return f
        exes = list(out.rglob("*.exe"))
        return exes[0] if exes else None
    except Exception as exc:  # noqa: BLE001
        core.log(f"解压失败: {exc}", level="ERROR", source="afterburner")
        return None


def silent_install(setup_exe: Path,
                   target: Path | None = None) -> dict[str, Any]:
    """静默安装到指定目录。

    Afterburner 安装器由 NSIS 打包，支持：
        /S          静默
        /D=<路径>   指定目录（必须放最后，且路径不加引号）
    若该版本不支持，则退回交互式安装向导。
    """
    target = target or (install_dir() / "runtime" / "MSI Afterburner")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    args = [str(setup_exe), "/S", f"/D={target}"]
    core.log(f"静默安装 Afterburner -> {target}", source="afterburner")
    proc = core.run(args, timeout=600)
    exe = target / "MSIAfterburner.exe"
    if exe.exists():
        return {"ok": True, "path": str(target), "rc": proc.returncode}
    core.log("静默安装未生效，改为交互式", level="WARN", source="afterburner")
    try:
        subprocess.Popen([str(setup_exe)], cwd=str(setup_exe.parent))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "interactive": True,
            "detail": "已打开安装向导，请手动完成安装",
            "rc": proc.returncode}


def full_install(progress: Callable[[str], None] | None = None
                 ) -> dict[str, Any]:
    """安装流程：已装 → 内嵌包 → 本地包 → 自动下载，都走严格校验。"""
    if is_installed():
        return {"ok": True, "already": True, "path": str(find())}

    # 1) 程序内嵌的安装包（最省事，无需联网）
    if bundled_zip() is not None:
        if progress:
            progress("使用程序内嵌的安装包…")
        r = install_from_bundled(progress)
        if r.get("ok"):
            return r
        if progress:
            progress(f"内嵌安装未成功：{r.get('error') or ''}")

    # 2) 用户手动放进来的安装包
    local = scan_manual_drop()
    if local.get("ok"):
        if progress:
            progress("发现本地安装包，校验通过，开始安装…")
        r = install_from_local(Path(local["file"]))
        r["source"] = "local"
        return r

    # 3) 尝试官方直链（会被 CDN 拦，但若通就赚到）
    dl = download(progress)
    if not dl.get("ok"):
        return {"ok": False, "stage": "download", "errors": dl.get("errors"),
                "hint": "没有可用的自动下载直链。MSI 官网的下载按钮指向 "
                        "Norton 推广包，本工具不会自动安装它。"
                        "请用「打开官方下载页」或从可信来源下载 Afterburner 后，"
                        f"把安装包放到：{download_dir()}"}
    if progress:
        progress("解压安装包…")
    setup = extract(Path(dl["path"]))
    if setup is None:
        return {"ok": False, "stage": "extract", "error": "未找到安装器"}
    if progress:
        progress("静默安装到程序目录…")
    r = silent_install(setup)
    r["setup"] = str(setup)
    return r


def cleanup() -> dict[str, Any]:
    removed = 0
    try:
        for f in download_dir().glob("MSIAfterburnerSetup*.zip"):
            f.unlink()
            removed += 1
        sd = download_dir() / "setup"
        if sd.exists():
            shutil.rmtree(sd, ignore_errors=True)
    except OSError:
        pass
    return {"ok": True, "removed": removed}


# --------------------------------------------------------------------------
# 内嵌安装包（随程序分发）
# --------------------------------------------------------------------------
def bundled_zip() -> Path | None:
    """程序自带的内嵌安装包位置。

    打包时会把 assets/MSIAfterburnerSetup.zip 一起打进 exe，
    运行时位于 sys._MEIPASS\\junkcleaner\\assets 下。
    """
    import sys
    base = getattr(sys, "_MEIPASS", None)
    roots = []
    if base:
        roots.append(Path(base) / "junkcleaner" / "assets")
    roots.append(Path(__file__).resolve().parent / "assets")
    for r in roots:
        for name in ("MSIAfterburnerSetup.zip", "MSIAfterburnerSetup.exe"):
            p = r / name
            if p.exists():
                return p
    return None


def install_from_bundled(progress: Callable[[str], None] | None = None
                         ) -> dict[str, Any]:
    """用内嵌的安装包静默安装（无需联网）。"""
    src = bundled_zip()
    if src is None:
        return {"ok": False, "stage": "bundled", "error": "未找到内嵌安装包"}
    if progress:
        progress(f"使用内嵌安装包 {src.name}")
    v = verify_installer(src)
    if not v.get("ok"):
        if v.get("kind") != "zip":
            return {"ok": False, "stage": "verify", "error": v.get("reason")}
    # 拷到可写目录再处理（_MEIPASS 是只读的临时目录）
    work = download_dir()
    local = work / src.name
    if str(src.resolve()) != str(local.resolve()):
        try:
            shutil.copy2(src, local)
        except OSError as exc:
            return {"ok": False, "stage": "copy", "error": str(exc)}
    if progress:
        progress("校验并静默安装…")
    r = install_from_local(local)
    r["source"] = "bundled"
    return r
