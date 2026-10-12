"""验证静默卸载的类型识别与参数选择（不实际卸载）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, silent_uninstall as su  # noqa: E402

CASES = [
    (r'"C:\Program Files\SogouInput\Uninstall\Uninstall.exe"', "", "generic"),
    (r"d:\Thunder\ThunderUninstall.exe", "", "generic"),
    (r"C:\App\unins000.exe", "", "inno"),
    (r"MsiExec.exe /X{GUID}", "", "msi"),
    (r"C:\App\uninstall.exe -remove", "", "installshield"),
    (r"C:\App\Uninstall.exe /S", "", "generic"),
]


def main() -> int:
    print("=" * 74)
    print("[1] 卸载器类型识别")
    fail = 0
    for cmd, quiet, expect in CASES:
        got = su.classify(cmd, quiet)
        ok = got == expect
        fail += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] {expect:<14} <- {cmd[:60]}")

    print("=" * 74)
    print("[2] 真实卸载项的类型与候选参数")
    for e in core.iter_uninstall_entries():
        name = e.get("display_name") or ""
        if not any(k in name for k in ("迅雷", "搜狗", "WPS", "百度网盘")):
            continue
        s = e.get("uninstall_string") or ""
        q = e.get("quiet_uninstall") or ""
        kind = su.classify(s, q)
        cmds = [("自带静默", su._split(q))] if q else []
        cmds += [(" ".join(a), su._split(s) + a)
                 for a in su.CANDIDATES.get(kind, [])[:3]]
        print(f"\n  {name}")
        print(f"    类型: {kind}")
        for label, argv in cmds:
            tail = " ".join(argv[-3:]) if len(argv) > 3 else ""
            print(f"    {label:<12} {Path(argv[0]).name if argv else '?'} {tail}")

    print("=" * 74)
    print("RESULT:", "PASS" if fail == 0 else f"FAIL({fail})")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
