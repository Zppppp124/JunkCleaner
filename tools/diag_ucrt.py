"""A/B 验证：_internal\\ucrtbase.dll 是否为 Qt 加载失败的原因。"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

CHILD = r"""
import ctypes, sys
p = sys.argv[1]
try:
    ctypes.WinDLL(p, winmode=0x00000008)
    print("LOADED_OK")
except OSError as e:
    print("FAIL", e.winerror)
"""


def probe(dll: Path) -> str:
    """在全新子进程里测试加载，避免当前进程污染。"""
    proc = subprocess.run([sys.executable, "-c", CHILD, str(dll)],
                          capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip()


def main() -> int:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\dist_min\minqt\_internal")
    qt = base / "PySide6" / "Qt6Core.dll"
    uc = base / "ucrtbase.dll"
    bak = base / "ucrtbase.dll.bak"

    print(f"目标: {base}")
    print("=" * 60)

    # 1) 放回 ucrtbase.dll
    if bak.exists():
        if uc.exists():
            uc.unlink()
        shutil.move(str(bak), str(uc))
        print("已恢复 _internal\\ucrtbase.dll")
    if uc.exists():
        print(f"ucrtbase 版本: {subprocess.run(['cmd','/c','ver'],capture_output=True,text=True).stdout.strip()[:0] or ''}")
        print(f"存在: {uc}")
    r1 = probe(qt)
    print(f"  [A] 带 ucrtbase.dll  -> {r1}")

    # 2) 移除 ucrtbase.dll
    if uc.exists():
        if bak.exists():
            bak.unlink()
        shutil.move(str(uc), str(bak))
        print("已移除 _internal\\ucrtbase.dll（重命名为 .bak）")
    r2 = probe(qt)
    print(f"  [B] 无 ucrtbase.dll  -> {r2}")

    print("=" * 60)
    if r1.startswith("FAIL") and r2 == "LOADED_OK":
        print("结论：_internal\\ucrtbase.dll 是冲突源（确认）")
    elif r2 == "LOADED_OK":
        print("结论：移除后可用（至少不再冲突）")
    else:
        print("结论：仍有其它问题")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
