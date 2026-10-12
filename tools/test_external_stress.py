"""验证「外部 Python 跑 CUDA 负载」这条路（打包后的 EXE 靠它）。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load  # noqa: E402


def main() -> int:
    print("=== 查找带 CUDA 的系统 Python ===")
    py = gpu_load.system_python_with_torch()
    print(f"找到: {py or '（无）'}")
    if not py:
        return 1
    print("=" * 70)

    base = gpu.read_state()
    print(f"闲置: {base.clock_graphics}MHz {base.power_draw:.0f}W "
          f"占用 {base.utilization}%")

    ext = gpu_load.ExternalStress(seconds=30)
    print(f"启动外部负载: {ext.start()}")
    peak = {"util": 0, "power": 0.0}
    for _ in range(7):
        time.sleep(2)
        st = gpu.read_state()
        peak["util"] = max(peak["util"], st.utilization)
        peak["power"] = max(peak["power"], st.power_draw)
        print(f"  {st.clock_graphics}MHz {st.temperature}°C "
              f"{st.power_draw:.0f}W 占用 {st.utilization}%")
    ext.stop()
    print("=" * 70)
    print(f"峰值: 占用 {peak['util']}%  功耗 {peak['power']:.0f}W")
    ok = peak["util"] >= 90
    print(f"外部负载有效: {'是' if ok else '否'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
