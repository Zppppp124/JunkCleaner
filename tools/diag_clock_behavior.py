"""验证「负载不够导致 GPU 不升频」的判断。

思路：用更高的负载强度（更大的矩阵 + 更多并发），看频率是否跟着上去。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu  # noqa: E402

HELPER = r"""
import sys, time, torch
torch.cuda.set_device(0)
size = int(sys.argv[1]); secs = float(sys.argv[2])
dt = torch.float16
a = torch.randn(size, size, device="cuda", dtype=dt) * 0.1
b = torch.randn(size, size, device="cuda", dtype=dt) * 0.1
end = time.time() + secs
n = 0
while time.time() < end:
    for _ in range(4):
        a = torch.relu(a @ b) * 0.001
        c = torch.matmul(a, b)
    torch.cuda.synchronize()
    n += 1
print("DONE", n)
"""


def run_load(size: int, secs: int, tag: str) -> tuple[int, float]:
    py = sys.executable
    p = subprocess.Popen([py, "-c", HELPER, str(size), str(secs)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(5)
    clocks, powers = [], []
    end = time.time() + max(1, secs - 5)
    while time.time() < end:
        st = gpu.read_state()
        clocks.append(st.clock_graphics)
        powers.append(st.power_draw)
        print(f"    {tag} sz={size}: {st.clock_graphics} MHz  "
              f"{st.power_draw:.0f}W  {st.temperature}°C  {st.utilization}%")
        time.sleep(3)
    try:
        p.terminate()
    except Exception:  # noqa: BLE001
        pass
    time.sleep(2)
    return (max(clocks) if clocks else 0, max(powers) if powers else 0.0)


def main() -> int:
    print("=" * 78)
    print("[1] 默认强度 4096")
    c1, p1 = run_load(4096, 14, "默认")
    print(f"   -> {c1} MHz, {p1:.0f} W")

    print("=" * 78)
    print("[2] 提高强度到 8192（更吃功耗）")
    c2, p2 = run_load(8192, 14, "加强")
    print(f"   -> {c2} MHz, {p2:.0f} W")

    print("=" * 78)
    print("[3] 拉高功耗墙并再测")
    st = gpu.read_state()
    print(f"  当前功耗墙 {st.power_limit:.0f}W / 上限 {st.power_max:.0f}W")
    r = gpu.set_power_limit(int(st.power_max))
    print(f"  设为上限: {r}")
    time.sleep(2)
    c3, p3 = run_load(8192, 14, "满墙")
    print(f"   -> {c3} MHz, {p3:.0f} W")

    print("=" * 78)
    print("[4] 结论")
    print(f"  默认负载   : {c1} MHz @ {p1:.0f}W")
    print(f"  加强负载   : {c2} MHz @ {p2:.0f}W")
    print(f"  加强+满墙  : {c3} MHz @ {p3:.0f}W")
    if max(c1, c2, c3) > 2760 + 30:
        print("  ✔ 频率会随负载/功耗上升 -> 之前是负载不够")
    else:
        print("  ✖ 加大负载也没用，另有原因")

    print("=" * 78)
    print("[5] 恢复")
    print("  reset clocks:", gpu.reset_clocks())
    print("  power back to 290:", gpu.set_power_limit(290))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
