"""实测 GPU 锁频 + 稳定性观察 + 恢复默认。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu  # noqa: E402


def main() -> int:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2700
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    print(f"=== 锁频到 {target}MHz，观察 {secs} 秒 ===")
    r = gpu.stability_test(target, seconds=secs,
                           progress=lambda m: print("   ", m))
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print("\n=== 恢复默认 ===")
    print(gpu.reset_clocks())
    time.sleep(2)
    st = gpu.read_state()
    print(f"恢复后 clock={st.clock_graphics} locked={st.locked_graphics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
