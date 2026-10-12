"""核对 Defender 策略值名是否真实存在（以官方 ADMX 为准）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import defender  # noqa: E402

ADMX = Path(r"C:\Windows\PolicyDefinitions\WindowsDefender.admx")


def main() -> int:
    raw = ADMX.read_text(encoding="utf-8", errors="replace")
    value_names = set(re.findall(r'valueName="([^"]+)"', raw))
    print(f"官方 ADMX 中共有 {len(value_names)} 个 valueName")
    print("=" * 74)

    bad: list[str] = []
    for preset, settings in defender.PRESETS.items():
        print(f"\n预设 [{preset}] 共 {len(settings)} 项:")
        for s in settings:
            ok = s.value in value_names
            if not ok:
                bad.append(f"{preset}:{s.value}")
            print(f"  [{'OK ' if ok else 'BAD'}] {s.value:<52} = {s.target}")

    print("=" * 74)
    if bad:
        print(f"发现 {len(bad)} 个值名在 ADMX 中不存在：")
        for b in sorted(set(bad)):
            print("   ", b)
        print("\n可用的相近候选：")
        for token in ("Archive", "Network", "Packed", "Heuristic", "Idle",
                      "Catchup", "Schedule", "Purge", "Pause"):
            cands = sorted(n for n in value_names if token.lower() in n.lower())
            if cands:
                print(f"   含 {token}: {cands[:6]}")
    else:
        print("所有值名均存在于官方 ADMX")
    print("\nRESULT:", "PASS" if not bad else "FAIL")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
