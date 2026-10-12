"""电源方案管理：识别 Win10/Win11 并启用「卓越性能」。

「卓越性能」(Ultimate Performance) 是微软为工作站提供的电源方案，
相比「高性能」进一步关闭了核心停歇延迟、提高了处理器响应，
GUID 固定为 e9a42b02-d5df-448d-aa00-03f14749eb61。

注意：电源方案一旦设为活动方案，本身就会持久化（写入注册表），
重启后依然生效，不需要额外交互。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, asdict
from typing import Any

from . import core

ULTIMATE_TEMPLATE_GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"
HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
BALANCED_GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"
POWER_SAVER_GUID = "a1841308-3541-4fab-bc81-f71556f20b4a"

KNOWN = {
    ULTIMATE_TEMPLATE_GUID: "卓越性能（模板，需先创建）",
    HIGH_PERF_GUID: "高性能",
    BALANCED_GUID: "平衡",
    POWER_SAVER_GUID: "节能",
}

# 卓越性能被创建后会得到新 GUID，因此必须按名字识别
ULTIMATE_NAMES = ("卓越性能", "Ultimate Performance")

# 推荐在该方案下微调的处理器设置（GUID → (友好名, 值, 单位))
PROCESSOR_TUNING = [
    ("bc5038f7-23e0-4960-96da-33abaf5935ec", "最大处理器状态", 100),
    ("893dee8e-2bef-41e0-89c6-b55d0929964c", "最小处理器状态", 5),
    ("94d3a615-a899-4ac5-ae2b-e4d8f634367f", "系统散热方式", 1),  # 1=主动
]


@dataclass
class PlanInfo:
    guid: str
    name: str
    active: bool
    is_ultimate: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def windows_info() -> dict[str, Any]:
    """识别系统版本。Build >= 22000 视为 Windows 11。"""
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$o=Get-CimInstance Win32_OperatingSystem;"
        "[pscustomobject]@{Caption=$o.Caption;Version=$o.Version;"
        "Build=[int]$o.BuildNumber;Arch=$o.OSArchitecture} "
        "| ConvertTo-Json -Compress")
    text = (core.run_powershell(script, timeout=45).stdout or b"").decode(
        "utf-8", "replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    build = int(data.get("Build") or 0)
    data["is_windows_11"] = build >= 22000
    data["family"] = "Windows 11" if build >= 22000 else (
        "Windows 10" if build >= 10240 else "更早版本")
    return data


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def list_plans() -> list[PlanInfo]:
    # 强制 UTF-8 输出，避免中文方案名乱码/解析失败
    proc = core.run_powershell("powercfg /list | Out-String", timeout=40)
    text = _decode(proc.stdout or b"")
    if not text.strip():
        proc = core.run(["powercfg", "/list"], timeout=40)
        text = _decode(proc.stdout or b"")
    plans: list[PlanInfo] = []
    # 匹配两种格式：
    #   电源方案 GUID: xxx  (名称) *
    #   Power Scheme GUID: xxx  (Name) *
    pattern = (r"GUID:\s*([0-9a-fA-F-]{36})\s*\(([^)]*)\)(\s*\*)?")
    for m in re.finditer(pattern, text):
        guid = m.group(1).lower()
        name = m.group(2).strip()
        active = bool(m.group(3))
        is_ult = any(n.lower() in name.lower() for n in ULTIMATE_NAMES)
        plans.append(PlanInfo(guid, name, active, is_ult))
    return plans


def current_plan() -> PlanInfo | None:
    for p in list_plans():
        if p.active:
            return p
    return None


def ultimate_exists() -> bool:
    return find_ultimate() is not None


def find_ultimate() -> PlanInfo | None:
    """按名称查找已创建的「卓越性能」方案（GUID 会因创建而变）。"""
    for p in list_plans():
        if any(n.lower() in p.name.lower() for n in ULTIMATE_NAMES):
            return p
    return None


def enable_ultimate() -> dict[str, Any]:
    """启用（必要时先创建）「卓越性能」方案，返回最终生效的 GUID。"""
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    created = False
    plan = find_ultimate()
    if plan is None:
        # 复制内置的卓越性能模板（会得到新 GUID）
        proc = core.run(["powercfg", "-duplicatescheme",
                         ULTIMATE_TEMPLATE_GUID], timeout=60)
        _decode(proc.stdout or b"")
        created = True
        plan = find_ultimate()
    if plan is None:
        # 模板不可用，退回高性能方案
        hp = next((p for p in list_plans() if p.guid == HIGH_PERF_GUID), None)
        if hp is None:
            proc = core.run(["powercfg", "-duplicatescheme", HIGH_PERF_GUID],
                            timeout=60)
            _decode(proc.stdout or b"")
            hp = next((p for p in list_plans() if p.guid == HIGH_PERF_GUID), None)
        if hp is None:
            return {"ok": False, "error": "无法创建卓越性能/高性能方案"}
        plan = hp
    proc = core.run(["powercfg", "/setactive", plan.guid], timeout=40)
    ok = proc.returncode == 0
    core.log(f"启用 {plan.name}({plan.guid}): {'成功' if ok else '失败'}",
             source="power")
    return {"ok": ok, "created": created, "guid": plan.guid,
            "name": plan.name,
            "detail": _decode(proc.stdout or b"").strip()}


def set_active(guid: str) -> dict[str, Any]:
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    proc = core.run(["powercfg", "/setactive", guid], timeout=40)
    ok = proc.returncode == 0
    core.log(f"切换电源方案 {guid}: {'成功' if ok else '失败'}", source="power")
    return {"ok": ok, "detail": _decode(proc.stdout or b"").strip()}


def tune_processor(guid: str | None = None) -> dict[str, Any]:
    """在指定方案下把处理器相关项调到性能优先。"""
    if not core.is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    if not guid:
        plan = find_ultimate() or current_plan()
        if plan is None:
            return {"ok": False, "error": "找不到可用电源方案"}
        guid = plan.guid
    results: list[str] = []
    for setting, label, value in PROCESSOR_TUNING:
        proc = core.run(["powercfg", "/setacvalueindex", guid,
                         "54533251-82be-4824-96c1-47b60b740d00",
                         setting, str(value)], timeout=30)
        results.append(f"{label}={'ok' if proc.returncode == 0 else 'fail'}")
    core.run(["powercfg", "/setactive", guid], timeout=30)
    core.log("处理器电源项调整: " + ", ".join(results), source="power")
    return {"ok": True, "results": results}


def plan_forbidden_reasons() -> list[str]:
    """列出可能影响方案生效的因素。"""
    reasons: list[str] = []
    info = windows_info()
    if info.get("family") == "Windows 11":
        reasons.append("Windows 11 默认隐藏「卓越性能」，需先创建")
    # 检查是否由组策略/厂商工具锁定
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Power") as k:
            try:
                winreg.QueryValueEx(k, "PlatformAoAcOverride")
                reasons.append("检测到 PlatformAoAcOverride（可能来自厂商工具）")
            except OSError:
                pass
    except OSError:
        pass
    return reasons
