"""验证 _internal 里的 api-ms-win-*.dll 是否破坏 Qt 加载。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

CHILD = r"""
import os, sys
d = sys.argv[1]
for sub in ('', 'PySide6', 'shiboken6'):
    p = os.path.join(d, sub) if sub else d
    if os.path.isdir(p):
        try: os.add_dll_directory(p)
        except Exception: pass
try:
    from PySide6 import QtCore
    print('QT_IMPORT_OK', QtCore.__version__)
except Exception as e:
    print('QT_IMPORT_FAIL', e)
"""


def child_import(internal: Path) -> str:
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, "-c", CHILD, str(internal)],
                          capture_output=True, env=env)
    return ((proc.stdout or b"") + (proc.stderr or b"")).decode(
        "utf-8", "replace").strip()


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\d2\minqt2")
    internal = root / "_internal"
    print(f"internal={internal}")
    print("=" * 70)

    apisets = sorted(p for p in internal.glob("api-ms-win-*.dll"))
    print(f"api-ms-win-*.dll 数量: {len(apisets)}")
    if apisets:
        print("  示例:", ", ".join(p.name for p in apisets[:5]))

    print("\n[BEFORE] import 测试:")
    print("  " + child_import(internal))

    if apisets:
        bak = internal / "_apiset_backup"
        bak.mkdir(exist_ok=True)
        for p in apisets:
            shutil.move(str(p), str(bak / p.name))
        print(f"\n已把 {len(apisets)} 个 api-ms-win-*.dll 移到 _apiset_backup\\")
        print("[AFTER] import 测试:")
        print("  " + child_import(internal))

        # 恢复
        for p in bak.iterdir():
            shutil.move(str(p), str(internal / p.name))
        bak.rmdir()
        print("\n已恢复")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
