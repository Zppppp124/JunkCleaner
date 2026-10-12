"""一键自检：语法、签名匹配、清理还原、拦截守护、GUI 冒烟。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("JUNKCLEANER_DATA", str(ROOT / "_runtime"))

MODULES = ["__init__.py", "signatures.py", "core.py", "scanner.py",
           "cleaner.py", "guard.py", "gui.py", "cli.py"]
SCRIPTS = ["test_signatures.py", "test_clean.py", "test_guard.py",
           "test_guard_live.py", "test_trust.py", "test_normal_apps.py",
           "test_protection.py", "test_bundle_child.py",
           "test_archive_trust.py", "test_gui_smoke.py"]


def run(title: str, args: list[str]) -> bool:
    print(f"\n===== {title} =====", flush=True)
    proc = subprocess.run(args, cwd=ROOT)
    return proc.returncode == 0


def main() -> int:
    results: list[tuple[str, bool]] = []
    py = sys.executable

    files = [str(ROOT / "junkcleaner" / m) for m in MODULES]
    files.append(str(ROOT / "junkcleaner_entry.py"))
    total = len(SCRIPTS) + 1
    results.append(("语法检查", run(f"1/{total} 语法检查",
                                    [py, "-m", "py_compile", *files])))
    for i, script in enumerate(SCRIPTS, start=2):
        results.append((script, run(f"{i}/{total} {script}",
                                    [py, str(ROOT / "tests" / script)])))

    print("\n" + "=" * 46)
    print("自检汇总：")
    for name, ok in results:
        print(f"  [{'通过' if ok else '失败'}] {name}")
    all_ok = all(ok for _, ok in results)
    print("=" * 46)
    print("结果：", "全部通过" if all_ok else "存在失败项")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
