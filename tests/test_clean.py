"""清理引擎沙箱测试：用临时目录 + HKCU 测试键验证清理与还原，全程可逆。"""

from __future__ import annotations

import json
import sys
import tempfile
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import cleaner, core  # noqa: E402

TEST_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\JunkCleanerSelfTest"


def _make_fake() -> tuple[Path, str]:
    root = Path(tempfile.mkdtemp(prefix="jc_clean_"))
    install = root / "FakeJunk"
    install.mkdir()
    (install / "junk.exe").write_bytes(b"MZ fake")
    (install / "data.bin").write_bytes(b"x" * 4096)

    subkey = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\JunkCleanerSelfTest"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, subkey) as k:
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, "360安全卫士自检")
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, "echo fake")
    return install, subkey


def _key_exists(subkey: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey):
            return True
    except OSError:
        return False


def main() -> int:
    install, subkey = _make_fake()
    finding = {
        "sig_id": "360.weishi",
        "name": "360安全卫士（自检）",
        "risk": "rogue",
        "uninstall_entries": [{"display_name": "360安全卫士自检", "publisher": "test",
                               "version": "1", "install_location": str(install),
                               "uninstall_string": "echo fake", "quiet_uninstall": "",
                               "hive": "HKCU", "subkey": subkey}],
        "processes": [], "services": [], "tasks": [], "startup": [],
        "paths": [str(install)],
    }
    report = cleaner.clean_finding(finding, uninstall=False, purge_files=True,
                                   log=lambda m: print("   ", m))
    moved = not install.exists()
    key_gone = not _key_exists(subkey)
    manifest = json.loads(Path(report.manifest).read_text(encoding="utf-8"))
    print(f"残留目录已隔离: {moved}")
    print(f"卸载注册表已删除: {key_gone}")
    print(f"清单记录: moves={len(manifest['moves'])} registry={len(manifest['registry'])}")
    print(f"隔离体积: {core.human_size(report.freed_bytes)}")

    # 还原
    actions = cleaner.restore_manifest(report.manifest)
    restored = install.exists() and (install / "junk.exe").exists()
    print(f"还原成功: {restored}  actions={sum(1 for a in actions if a.ok)}/{len(actions)}")

    ok = moved and key_gone and restored and report.freed_bytes > 0
    print("\nRESULT:", "PASS" if ok else "FAIL")
    # 清理测试痕迹
    try:
        if install.exists():
            for f in install.rglob("*"):
                f.unlink()
            install.rmdir()
            install.parent.rmdir()
    except OSError:
        pass
    try:
        cleaner.delete_registry_key(winreg.HKEY_CURRENT_USER, subkey)
    except Exception:  # noqa: BLE001
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
