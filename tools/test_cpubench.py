"""验证 CPU 跑分与压力测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import cpubench  # noqa: E402


def main() -> int:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print("=" * 70)
    print("CPU 跑分（单核 + 多核）")
    print("=" * 70)
    r = cpubench.benchmark(progress=lambda m: print("  ", m))
    print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
    print(f"\n单核 {r.single_score:.1f} 分　多核 {r.multi_score:.1f} 分　"
          f"多核倍率 {r.ratio:.2f}x（{r.threads} 线程）")

    print("=" * 70)
    print(f"CPU 压力测试 {secs} 秒")
    print("=" * 70)
    s = cpubench.cpu_stress(seconds=secs, progress=lambda m: print("  ", m))
    print(json.dumps({k: v for k, v in s.items() if k != "detail"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
