"""在完全干净的 PATH 下运行打包好的 exe，判断是否是 PATH 污染导致。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run_case(label: str, exe: Path, path_value: str) -> None:
    env = dict(os.environ)
    env["PATH"] = path_value
    print(f"--- {label}")
    print(f"    PATH={path_value[:90]}")
    try:
        proc = subprocess.run([str(exe)], capture_output=True, timeout=90,
                              env=env, cwd=str(exe.parent))
        out = ((proc.stdout or b"") + (proc.stderr or b"")).decode(
            "utf-8", "replace").strip()
        print(f"    rc={proc.returncode}")
        for line in out.splitlines()[:6]:
            print(f"    | {line}")
    except subprocess.TimeoutExpired:
        print("    超时（可能已成功启动 GUI）")


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"I:\CODEX\JunkCleaner\dist\JunkCleaner_dbg.exe")
    if not exe.exists():
        print(f"找不到 {exe}")
        return 1
    sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    sys32b = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32", "Wbem")

    run_case("1) 仅 System32（最干净）", exe, sys32)
    run_case("2) System32 + Wbem", exe, sys32 + os.pathsep + sys32b)
    run_case("3) 当前完整 PATH（对照）", exe, os.environ.get("PATH", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
