"""验证某一档 V/F 点的稳定性（带数值校验的瞬态负载）。

用法：python tools\verify_uv_point.py <目标频率MHz> [测试秒数]
只做负载与校验，不改动任何显卡设置。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu_load  # noqa: E402


def main() -> int:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 2850
    secs = int(sys.argv[2]) if len(sys.argv) > 2 else 45

    s = gpu_load.GpuStress(transient=True, high_ms=120, low_ms=60)
    s.start()
    time.sleep(2)
    if not s.running:
        print("LOAD_FAIL", s.errors)
        return 1

    clocks: list[float] = []
    powers: list[float] = []
    temps: list[int] = []
    utils: list[int] = []
    end = time.time() + secs
    while time.time() < end:
        time.sleep(1.0)
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=clocks.gr,power.draw,temperature.gpu,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True).stdout.strip()
        try:
            parts = [p.strip() for p in out.split(",")]
            clocks.append(float(parts[0].replace("MHz", "").strip()))
            powers.append(float(parts[1].replace("W", "").strip()))
            temps.append(int(parts[2].strip()))
            utils.append(int(parts[3].replace("%", "").strip()))
        except Exception:  # noqa: BLE001
            continue
    s.stop()

    runner = getattr(s, "_opencl", None) or getattr(s, "_external", None)
    corrupt = runner.corruption() if runner is not None else ""
    errs = s.summary()["errors"]
    # 只统计「真正处于满载」的样本：瞬态模式会在轻载与满载间跳变，
    # 低载样本的时钟天然很低，把它们算进去会误报「掉频」。
    busy = [(c, p) for c, p, u in zip(clocks, powers, utils) if u >= 90]
    busy_clocks = [c for c, _ in busy]
    avg = sum(busy_clocks) / len(busy_clocks) if busy_clocks else 0
    dropped = sum(1 for c in busy_clocks if c < target * 0.95)
    print(f"samples={len(clocks)} busy(util>=90%)={len(busy_clocks)}")
    print(f"busy clocks avg={avg:.0f} min={min(busy_clocks, default=0):.0f} "
          f"max={max(busy_clocks, default=0):.0f} dropped={dropped}")
    print(f"power max={max(powers, default=0):.0f}W util max={max(utils, default=0)}% "
          f"temp max={max(temps, default=0)}C")
    print(f"corruption={corrupt!r} errors={errs}")
    if not busy_clocks:
        print("VERDICT: NO_BUSY_SAMPLES")
        return 2
    ok = dropped == 0 and not corrupt and not errs
    print("VERDICT:", "STABLE" if ok else "UNSTABLE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
