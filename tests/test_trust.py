"""可信白名单测试：信任后扫描跳过、拦截放行、显式拦截优先。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import scanner, trust  # noqa: E402


def main() -> int:
    # 1) 命中白名单：迅雷被信任后应标记 trusted 且不勾选
    entry = trust.add_trust("迅雷", "name", "迅雷", source="test")
    found = scanner.scan(include_disputed=True, compute_size=False)
    row = next((f for f in found if f.sig_id == "xunlei.main"), None)
    trusted_ok = bool(row and row.trusted and not row.selected)
    print(f"信任后扫描标记: trusted={getattr(row,'trusted',None)} "
          f"selected={getattr(row,'selected',None)}")

    # 2) 显式拦截名单优先于白名单
    blocked_entry = trust.add_blocked("迅雷", "迅雷")
    found2 = scanner.scan(include_disputed=True, compute_size=False)
    row2 = next((f for f in found2 if f.sig_id == "xunlei.main"), None)
    blocked_ok = bool(row2 and not row2.trusted and row2.selected)
    print(f"拦截名单优先: trusted={getattr(row2,'trusted',None)} "
          f"selected={getattr(row2,'selected',None)}")

    # 3) 精确匹配函数
    path_entry = trust.add_trust("测试目录", "path", r"C:\TestApp", source="test")
    m1 = trust.matches(exe_path=r"C:\TestApp\bin\run.exe")
    m2 = trust.matches(exe_path=r"C:\Other\run.exe")
    hash_entry = trust.add_trust("测试指纹", "hash", "abc123", source="test")
    m3 = trust.matches(file_hash="abc123")
    print(f"路径前缀匹配: {bool(m1)}  非前缀: {bool(m2)}  指纹匹配: {bool(m3)}")

    # 清理
    for e in (entry, blocked_entry, path_entry, hash_entry):
        trust.remove_trust(e["id"])
        trust.remove_blocked(e["id"])
    ok = trusted_ok and blocked_ok and bool(m1) and not m2 and bool(m3)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
