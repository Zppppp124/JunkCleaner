"""验证「Afterburner 覆盖 nvidia-smi 锁频」的假设。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load, vfcurve  # noqa: E402


def procs() -> list[dict]:
    try:
        import psutil
        return [{"pid": p.info["pid"], "name": p.info["name"]}
                for p in psutil.process_iter(["pid", "name"])
                if (p.info.get("name") or "").lower() in
                ("msiafterburner.exe", "rtss.exe")]
    except Exception:  # noqa: BLE001
        return []


def load_and_report(tag: str, seconds: int = 9) -> int:
    """跑负载并返回稳定后的频率。"""
    loader = gpu_load.GpuStress()
    loader.start()
    try:
        time.sleep(4)
        clocks = []
        for _ in range(3):
            time.sleep(2)
            st = gpu.read_state()
            clocks.append(st.clock_graphics)
            print(f"    {tag}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
                  f"{st.temperature}°C  {st.utilization}%")
        return max(clocks) if clocks else 0
    finally:
        loader.stop()
        time.sleep(2)


def main() -> int:
    print("=" * 78)
    print("[1] 进程状态")
    print("   ", procs() or "（无 Afterburner / RTSS）")

    print("=" * 78)
    print("[2] 基线：Afterburner 运行中，nvidia-smi 锁 2850")
    gpu.reset_clocks()
    time.sleep(2)
    print("   lock:", gpu.lock_clocks(2850))
    c1 = load_and_report("AB运行")
    print(f"   -> 最高 {c1} MHz")

    print("=" * 78)
    print("[3] 停掉 Afterburner，重试同样的锁频")
    stopped = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            if (p.info.get("name") or "").lower() == "msiafterburner.exe":
                p.kill()
                stopped.append(p.info["pid"])
    except Exception as exc:  # noqa: BLE001
        print("   停止失败:", exc)
    print(f"   已停止 Afterburner: {stopped}")
    time.sleep(3)
    print("   lock:", gpu.lock_clocks(2850))
    c2 = load_and_report("AB已停")
    print(f"   -> 最高 {c2} MHz")

    print("=" * 78)
    print("[4] 结论")
    if c2 > c1 + 30:
        print(f"   ✔ 确认是 Afterburner 覆盖了 nvidia-smi 的锁频")
        print(f"     Afterburner 运行时 {c1} MHz，停止后 {c2} MHz")
    elif abs(c2 - c1) < 30:
        print(f"   两种情况下频率相同（{c1} vs {c2}），不是 Afterburner 的问题")
        print("   可能是显卡固件/曲线的实际上限就在这个值附近")
    else:
        print(f"   结果异常：AB运行={c1}  AB停止={c2}")

    print("=" * 78)
    print("[5] 复位并恢复 Afterburner")
    print("   reset:", gpu.reset_clocks())
    ab = Path(r"D:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe")
    if ab.exists():
        try:
            subprocess.Popen([str(ab)], cwd=str(ab.parent))
            print("   已重新启动 Afterburner")
        except Exception as exc:  # noqa: BLE001
            print("   启动失败:", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
