"""检查 QtCore.pyd 的依赖是否齐全（递归一层）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pe_imports import read_imports  # noqa: E402


def main() -> int:
    internal = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\d2\minqt2\_internal")
    ps = internal / "PySide6"
    shiboken = internal / "shiboken6"
    search = [ps, internal, shiboken]
    target = ps / "QtCore.pyd"

    print(f"检查 {target}")
    print("=" * 70)
    missing: list[str] = []
    for name in read_imports(target):
        low = name.lower()
        # 系统 DLL 交给系统解析
        if low.startswith("api-ms-win-") or low in {
                "kernel32.dll", "user32.dll", "advapi32.dll", "shell32.dll",
                "ole32.dll", "oleaut32.dll", "version.dll", "winmm.dll",
                "ws2_32.dll", "ntdll.dll", "mpr.dll", "userenv.dll",
                "authz.dll", "netapi32.dll"}:
            continue
        found = None
        for d in search:
            p = d / name
            if p.exists():
                found = p
                break
        if found:
            print(f"  [有] {name:<26} {found.parent.name}")
        else:
            print(f"  [缺] {name:<26} <<< 缺失")
            missing.append(name)
    print("=" * 70)
    print("缺失:", missing or "无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
