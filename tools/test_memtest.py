"""验证内存测试模块。"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import memtest  # noqa: E402


def main() -> int:
    total, free = memtest.available_memory()
    print(f"总内存 {total:.1f} GB，可用 {free:.1f} GB")
    print("=" * 70)
    t = memtest.MemTester(alloc_mb=1024, threads=4, rounds=1,
                          progress=lambda m: print("  ", m))
    r = t.run()
    d = r.to_dict()
    print("=" * 70)
    print(json.dumps(d, ensure_ascii=False, indent=2)[:1500])
    print("=" * 70)
    print(f"结论: {'通过（无错误）' if not r.errors else f'发现 {len(r.errors)} 个错误'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
