"""决定性验证：Afterburner 是否覆盖了 nvidia-smi 的锁频。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import gpu, gpu_load  # noqa: E402

AB = Path(r"D:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe")


def ab_procs() -> list[tuple[int, str]]:
    try:
        import psutil
        out = []
        for p in psutil.process_iter(["pid", "name"]):
            n = (p.info.get("name") or "").lower()
            if n in ("msiafterburner.exe", "rtss.exe", "rtsshooksloader64.exe"):
                out.append((p.info["pid"], p.info["name"]))
        return out
    except Exception:  # noqa: BLE001
        return []


def kill_ab() -> list[int]:
    killed = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            n = (p.info.get("name") or "").lower()
            if n in ("msiafterburner.exe", "rtss.exe", "rtsshooksloader64.exe"):
                p.kill()
                killed.append(p.info["pid"])
    except Exception:  # noqa: BLE001
        pass
    return killed


def measure(tag: str, secs: int = 12) -> int:
    loader = gpu_load.GpuStress()
    loader.start()
    try:
        time.sleep(4)
        clocks = []
        for _ in range(3):
            time.sleep(2.5)
            st = gpu.read_state()
            clocks.append(st.clock_graphics)
            print(f"    {tag}: {st.clock_graphics} MHz  {st.power_draw:.0f}W  "
                  f"{st.temperature}°C  {st.utilization}%")
        return max(clocks) if clocks else 0
    finally:
        loader.stop()
        time.sleep(2)


def main() -> int:
    print("=" * 80)
    print("[1] 当前进程")
    print("   ", ab_procs())

    print("=" * 80)
    print("[2] 场景A：Afterburner 运行中，锁 2850")
    gpu.reset_clocks()
    time.sleep(2)
    gpu.lock_clocks(2850)
    a = measure("AB运行")
    print(f"   -> 最高 {a} MHz")

    print("=" * 80)
    print("[3] 场景B：结束 Afterburner（含 RTSS），重新锁 2850")
    killed = kill_ab()
    print(f"   已结束进程: {killed}")
    time.sleep(4)
    print(f"   剩余: {ab_procs()}")
    gpu.reset_clocks()
    time.sleep(2)
    gpu.lock_clocks(2850)
    b = measure("AB已停")
    print(f"   -> 最高 {b} MHz")

    print("=" * 80)
    print("[4] 结论")
    if b > a + 40:
        print(f"   ✔ 确认：Afterburner 覆盖了 nvidia-smi 锁频")
        print(f"     AB运行 {a} MHz  →  AB停止 {b} MHz")
    else:
        print(f"   ✖ 不是 Afterburner 的问题（{a} vs {b}）")

    print("=" * 80)
    print("[5] 复位 + 恢复 Afterburner")
    print("   reset:", gpu.reset_clocks())
    if AB.exists():
        subprocess.Popen([str(AB)], cwd=str(AB.parent))
        print("   已重新启动 Afterburner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
