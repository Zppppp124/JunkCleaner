"""探测卸载项的静默卸载能力。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, scanner, signatures  # noqa: E402

# 各卸载器常见的静默开关
SILENT_FLAGS = {
    "nsis": ["/S"],
    "inno": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
    "installshield": ["/s", "/f1\"\"", "/qn"],
    "msi": ["/qn", "/norestart", "REBOOT=ReallySuppress"],
    "wise": ["/s", "/silent"],
    "generic": ["/S", "/silent", "/quiet", "/qn", "/VERYSILENT"],
}


def classify(cmd: str) -> str:
    low = (cmd or "").lower()
    if "msiexec" in low or low.endswith(".msi"):
        return "msi"
    if "unins" in low or "uninstall" in low:
        return "generic"
    if "nsis" in low:
        return "nsis"
    return "generic"


def main() -> int:
    rows = list(core.iter_uninstall_entries())
    print(f"卸载项总数: {len(rows)}")
    print("=" * 78)
    interesting = []
    for e in rows:
        name = e.get("display_name") or ""
        sigs = [s["id"] for s in signatures.SIGNATURES
                if any(re.search(p, name, re.I)
                       for p in s.get("uninstall") or [])]
        if sigs:
            interesting.append((name, e, sigs))
    print(f"命中的垃圾软件卸载项: {len(interesting)}")
    for name, e, sigs in interesting[:15]:
        print("=" * 78)
        print(f"名称  : {name}")
        print(f"家族  : {sigs}")
        print(f"发行商: {e.get('publisher')}")
        print(f"卸载串: {e.get('uninstall_string')}")
        print(f"静默串: {e.get('quiet_uninstall')}")
        kind = classify(e.get("uninstall_string") or "")
        print(f"类型  : {kind}  建议静默开关: {SILENT_FLAGS.get(kind)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
