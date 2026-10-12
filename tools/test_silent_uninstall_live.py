"""静默卸载实测：用 HKCU 假卸载项 + 假卸载器验证完整流程。"""

from __future__ import annotations

import sys
import tempfile
import time
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, silent_uninstall as su  # noqa: E402

SUBKEY = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
          r"\JunkCleanerSilentTest")


def make_fake_uninstaller() -> Path:
    """造一个会自己删除注册表项的假卸载器（bat）。"""
    d = Path(tempfile.mkdtemp(prefix="jc_su_"))
    bat = d / "uninstall.bat"
    # 模拟「静默卸载」：删掉注册表项 + 建一个标记文件
    bat.write_text(
        "@echo off\r\n"
        "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion"
        "\\Uninstall\\JunkCleanerSilentTest\" /f >nul 2>nul\r\n"
        f"echo done > \"{d / 'uninstalled.txt'}\"\r\n",
        encoding="ascii")
    return bat


def main() -> int:
    bat = make_fake_uninstaller()
    print(f"假卸载器: {bat}")

    # 造一个卸载项，UninstallString 指向 bat（不带静默参数，测试参数推断）
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, SUBKEY) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ,
                          "静默卸载测试项")
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          f'"{bat}"')
    print("已创建 HKCU 假卸载项")
    print("=" * 74)

    entry = {
        "display_name": "静默卸载测试项",
        "uninstall_string": f'"{bat}"',
        "quiet_uninstall": "",
        "hive": "HKCU",
        "subkey": SUBKEY,
    }
    res = su.silent_uninstall(entry, timeout=60,
                              log=lambda m: print("  ", m))
    print("=" * 74)
    print(f"结果: {res.to_dict()}")

    still = True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SUBKEY):
            pass
    except OSError:
        still = False
    print(f"注册表项已移除: {not still}")
    print("RESULT:", "PASS" if res.ok and not still else "FAIL")

    # 清理
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, SUBKEY)
    except OSError:
        pass
    for f in bat.parent.iterdir():
        f.unlink(missing_ok=True)
    bat.parent.rmdir()
    return 0 if (res.ok and not still) else 1


if __name__ == "__main__":
    raise SystemExit(main())
