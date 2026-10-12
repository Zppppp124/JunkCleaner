"""签名库匹配自检：确保典型软件名能被正确识别，且正常软件不被误判。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import signatures  # noqa: E402
from junkcleaner.scanner import _hits  # noqa: E402

# (显示名 或 进程名, 期望命中的签名 id 或 None)
CASES: list[tuple[str, str | None]] = [
    ("360安全卫士", "360.weishi"),
    ("360杀毒", "360.antivirus"),
    ("360安全浏览器", "360.browser"),
    ("360压缩", "360.zip"),
    ("360驱动大师", "360.driver"),
    ("腾讯电脑管家", "tencent.pcmgr"),
    ("QQ浏览器", "tencent.browser"),
    ("应用宝", "tencent.appstore"),
    ("微软电脑管家", "microsoft.pcmgr"),
    ("2345加速浏览器", "2345.nav"),
    ("2345好压", "2345.haozip"),
    ("金山毒霸", "kingsoft.antivirus"),
    ("猎豹安全浏览器", "kingsoft.cheetah"),
    ("鲁大师", "ludashi.main"),
    ("驱动精灵", "driver.gene"),
    ("驱动人生", "driver.life"),
    ("百度卫士", "baidu.guard"),
    ("搜狗输入法 16.6", None),      # 正常档，不算垃圾软件
    ("迅雷", "xunlei.main"),
    ("暴风影音", "media.baofeng"),
    ("Flash中心", "flash.cn"),
    ("快压", "rar.bundled"),
    ("小鸟壁纸", "desktop.bird"),
    ("UC浏览器", "uc.browser"),
    ("瑞星杀毒", "rising.main"),
    ("江民杀毒", "jiangmin.main"),
    ("C盘瘦身", "misc.cleaner"),
    ("影视大全", "misc.video"),
    ("WiFi万能钥匙", "misc.wifi"),
    ("数据恢复大师", "misc.data"),
    ("PDF转换器", "misc.pdf"),
    ("游戏盒子", "game.box"),
    ("刷机大师", "mobile.assistant"),
    ("万能工具箱", "misc.toolbox"),
    ("网络加速器", "misc.wifi"),
    # 正常软件，不应命中
    ("微信", None),
    ("WPS Office", None),
    ("Microsoft Visual Studio Code", None),
    ("Adobe Photoshop 2026", None),
    ("MiHoYo 崩坏：星穹铁道", None),
    ("Blender", None),
    ("Git", None),
]

PROC_CASES: list[tuple[str, str | None]] = [
    ("360tray.exe", "360.weishi"),
    ("QQPCTray.exe", "tencent.pcmgr"),
    ("2345Explorer.exe", "2345.nav"),
    ("SogouImeBroker.exe", "sogou.input"),
    ("Thunder.exe", "xunlei.main"),
    ("FlashHelperService.exe", "flash.cn"),
    ("chrome.exe", None),
    ("Code.exe", None),
]


def main() -> int:
    failures = 0
    for name, expected in CASES:
        hits = [s for s in signatures.SIGNATURES if _hits(s["uninstall"], name)]
        # normal 档（如 WPS）不算「垃圾软件」命中
        matched = [s["id"] for s in hits if s["risk"] != "normal"]
        normal_hit = [s["id"] for s in hits if s["risk"] == "normal"]
        ok = (expected in matched) if expected else (not matched)
        mark = "ok " if ok else "FAIL"
        suffix = f"（正常档 {normal_hit}）" if normal_hit else ""
        print(f"[{mark}] {name:<32} -> {matched or '无'}{suffix}")
        failures += 0 if ok else 1
    print()
    for proc, expected in PROC_CASES:
        matched = [s["id"] for s in signatures.SIGNATURES
                   if _hits(s["process"], proc)]
        ok = (expected in matched) if expected else (not matched)
        mark = "ok " if ok else "FAIL"
        print(f"[{mark}] {proc:<32} -> {matched or '无'}")
        failures += 0 if ok else 1
    print(f"\n签名总数: {len(signatures.SIGNATURES)}  失败: {failures}")
    print("RESULT:", "PASS" if failures == 0 else "FAIL")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
