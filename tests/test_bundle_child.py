"""父子进程决策测试：正常软件(WPS/搜狗)拉起的第三方安装应被拒，
自己的正常子进程与普通程序拉起的进程不受影响。

用打桩方式直接验证判定逻辑，避免真实进程时序带来的不确定性。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import guard  # noqa: E402

TEMP_EXE = r"C:\Users\Admin\AppData\Local\Temp\jc_x\Setup_Tool.exe"
ROGUE_EXE = r"C:\Users\Admin\AppData\Local\Temp\jc_x\极速下载器_安装管家.exe"


def decide(parent_name: str, exe: str, name: str) -> str:
    """调用真实的 _handle_process 决策链，返回处置结果。"""
    watcher = guard.InstallerWatcher(notify=lambda *_: None, interval=1.0)
    killed: list[tuple] = []
    watcher._parent_of = lambda _pid: {"pid": "1", "name": parent_name, "exe": parent_name}
    watcher._kill = lambda pid, target, reason, sig: killed.append((target, reason, sig))
    watcher._handle_process({"pid": 424242, "name": name, "exe": exe,
                             "cmdline": f'"{exe}"'})
    return killed[0][1] if killed else "放行"


def main() -> int:
    cases = [
        # (说明, 父进程, 子进程路径, 子进程名, 期望：是否应被拒)
        ("WPS 拉起 Temp 下的捆绑安装器", "wps.exe", TEMP_EXE, "Setup_Tool.exe", True),
        ("搜狗拉起第三方捆绑器", "SGTool.exe", ROGUE_EXE, "极速下载器_安装管家.exe", True),
        ("WPS 的自身正常子进程", "wps.exe",
         r"C:\Program Files\WPS Office\wpscloudsvr.exe", "wpscloudsvr.exe", False),
        ("WPS 拉起系统正常工具", "wps.exe",
         r"C:\Windows\System32\notepad.exe", "notepad.exe", False),
        ("非正常软件(parent=chrome)拉起同类安装器", "chrome.exe", ROGUE_EXE,
         "极速下载器_安装管家.exe", True),   # 由签名层拦截，非父子规则
        ("普通程序拉起无特征临时程序", "chrome.exe",
         r"C:\Users\Admin\AppData\Local\Temp\jc_x\Setup_Tool.exe",
         "Setup_Tool.exe", False),
    ]
    failures = 0
    for desc, parent, exe, name, expect_block in cases:
        result = decide(parent, exe, name)
        blocked = result != "放行"
        ok = blocked == expect_block
        failures += 0 if ok else 1
        mark = "ok " if ok else "FAIL"
        print(f"[{mark}] {desc:<38} 父={parent:<12} -> {result}")

    print(f"\n失败: {failures}")
    print("RESULT:", "PASS" if failures == 0 else "FAIL")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
