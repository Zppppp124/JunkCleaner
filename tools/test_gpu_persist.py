"""测试 GPU 配置固化与开机应用。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from junkcleaner import core, gpu  # noqa: E402


def main() -> int:
    print("=" * 70)
    print("[1] 保存配置")
    p = gpu.save_profile(2700, 0, 290)
    print(f"    {p}")
    print(json.dumps(gpu.load_profile(), ensure_ascii=False, indent=2))

    print("=" * 70)
    print("[2] 注册开机任务")
    r = gpu.install_autostart()
    print(f"    {r}")
    print(f"    任务已安装: {gpu.autostart_installed()}")

    print("=" * 70)
    print("[3] 模拟开机：应用保存的配置")
    print(f"    {gpu.apply_saved_profile()}")

    print("=" * 70)
    print("[4] 清理：移除任务 + 恢复默认")
    print(f"    移除任务: {gpu.remove_autostart()}")
    print(f"    任务仍存在: {gpu.autostart_installed()}")
    print(f"    恢复默认: {gpu.reset_clocks()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
