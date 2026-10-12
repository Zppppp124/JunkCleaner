"""保护规则测试：C 盘垃圾软件可清，正常软件与系统目录不被误伤。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import cleaner  # noqa: E402

# (路径, 是否应被保护, 说明)
CASES: list[tuple[str, bool, str]] = [
    # ---- C 盘垃圾软件：必须可清理 ----
    (r"C:\ProgramData\Tencent\QQPCMgr", False, "腾讯电脑管家残留（关键回归）"),
    (r"C:\Program Files (x86)\Tencent\QQPCMgr", False, "腾讯电脑管家安装目录"),
    (r"C:\Users\Admin\AppData\Local\Tencent\QQPCMgr", False, "管家用户数据"),
    (r"C:\Program Files\360\360Safe", False, "360安全卫士"),
    (r"C:\Program Files (x86)\2345Explorer", False, "2345浏览器"),
    (r"C:\ProgramData\Thunder Network", False, "迅雷"),
    (r"C:\Program Files (x86)\Kingsoft\Antivirus", False, "金山毒霸"),
    (r"C:\Program Files (x86)\LuDaShi", False, "鲁大师"),
    # System32 下的文件不做清理，风险过高；Flash 只清 ProgramData/Program Files 部分
    (r"C:\Windows\System32\Macromed\Flash", True, "System32 保持保护（安全优先）"),
    (r"C:\ProgramData\FlashHelperService", False, "FlashHelperService"),
    (r"C:\Program Files\Microsoft PC Manager", False, "微软电脑管家（目标软件）"),
    (r"C:\Program Files (x86)\SogouExplorer", False, "搜狗浏览器（垃圾组件）"),
    (r"C:\Program Files (x86)\Baidu\BaiduSd", False, "百度杀毒"),
    (r"C:\Program Files\HaoZip", False, "好压"),
    # ---- 正常软件：必须保护 ----
    (r"C:\Program Files (x86)\Tencent\QQ\Bin", True, "QQ"),
    (r"C:\Program Files\Tencent\WeChat", True, "微信"),
    (r"C:\ProgramData\Tencent\WeChat", True, "微信数据"),
    (r"C:\Program Files\WPS Office", True, "WPS Office"),
    (r"C:\Program Files (x86)\SogouInput", True, "搜狗输入法"),
    (r"C:\Program Files\Google\Chrome\Application", True, "Chrome"),
    (r"C:\Program Files\Adobe\Adobe Photoshop 2026", True, "Photoshop"),
    (r"C:\Program Files\Autodesk\AutoCAD 2025", True, "AutoCAD"),
    (r"C:\Program Files\NVIDIA Corporation", True, "NVIDIA"),
    (r"C:\Program Files\nodejs", True, "Node.js"),
    (r"C:\Program Files\Git", True, "Git"),
    (r"C:\Program Files\Blender Foundation", True, "Blender"),
    (r"C:\Program Files\Java\jdk-17", True, "JDK"),
    (r"C:\Program Files\Microsoft\Edge", True, "Edge"),
    # ---- 会误伤旧版规则的同形目录（回归） ----
    (r"C:\Program Files\Digital\App", False, "Digital 不应被当成 git"),
    (r"C:\Program Files\Javascript\App", False, "Javascript 不应被当成 java"),
    # ---- 系统根：必须保护 ----
    (r"C:\Windows", True, "Windows 根"),
    (r"C:\Windows\System32", True, "System32"),
    (r"C:\Program Files", True, "Program Files 根"),
    (r"C:\ProgramData", True, "ProgramData 根"),
    (r"C:\Users", True, "Users 根"),
]


def main() -> int:
    failures = 0
    for path, should_protect, desc in CASES:
        actual = cleaner._is_protected(Path(path))
        ok = actual == should_protect
        failures += 0 if ok else 1
        mark = "ok " if ok else "FAIL"
        reason = cleaner.protection_reason(path) or "-"
        action = "保护" if actual else "可清理"
        print(f"[{mark}] {action:<4} {desc:<26} {path}")
        if not ok:
            print(f"       期望 {'保护' if should_protect else '可清理'}，"
                  f"实际 {action}（{reason}）")
    print(f"\n用例 {len(CASES)}  失败 {failures}")
    print("RESULT:", "PASS" if failures == 0 else "FAIL")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
