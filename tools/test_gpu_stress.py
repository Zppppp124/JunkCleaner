"""验证 GPU 满载压力测试是否真的把显卡打满。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load  # noqa: E402


def main() -> int:
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"CUDA 可用: {gpu_load.cuda_available()}")
    print(f"设备: {gpu_load.device_name()}")
    print("=" * 70)

    base = gpu.read_state()
    print(f"闲置: {base.clock_graphics}MHz  {base.temperature}°C  "
          f"{base.power_draw:.0f}W  占用 {base.utilization}%")
    print("=" * 70)
    print(f"启动满载压力测试 {secs} 秒 …")

    loader = gpu_load.GpuStress()
    loader.start()
    peak = {"util": 0, "power": 0.0, "temp": 0, "clock": 0}
    t0 = time.time()
    while time.time() - t0 < secs:
        st = gpu.read_state()
        peak["util"] = max(peak["util"], st.utilization)
        peak["power"] = max(peak["power"], st.power_draw)
        peak["temp"] = max(peak["temp"], st.temperature)
        peak["clock"] = max(peak["clock"], st.clock_graphics)
        print(f"  {st.clock_graphics}MHz  {st.temperature}°C  "
              f"{st.power_draw:.0f}W  占用 {st.utilization}%")
        time.sleep(2)
    loader.stop()

    print("=" * 70)
    print(f"峰值: 占用 {peak['util']}%  功耗 {peak['power']:.0f}W  "
          f"温度 {peak['temp']}°C  频率 {peak['clock']}MHz")
    print(f"负载轮数: {loader.iterations}  错误: {loader.errors[:2] or '无'}")
    ok = peak["util"] >= 90 and peak["power"] > base.power_draw * 1.5
    print(f"\n负载有效性: {'有效（真正打满）' if ok else '不足'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
