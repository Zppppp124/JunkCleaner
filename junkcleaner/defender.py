"""Windows Defender 组策略优化：把「扫描」页的性能损耗压到最低，同时保留扫描能力。

对应界面：计算机配置 > 管理模板 > Windows 组件 > Microsoft Defender 防病毒 > 扫描
对应注册表：HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows Defender\\Scan

安全边界（重要）
---------------
* 只动「扫描」相关策略，**不碰实时保护**（DisableRealtimeMonitoring、
  DisableAntiSpyware 等一律不涉及），也不会关闭 Defender 本身。
* 所有改动先完整备份，可一键还原。
* 提供两档：平衡（几乎零安全损失）/ 激进（最低开销，有真实安全代价）。
"""

from __future__ import annotations

import ctypes
import datetime as _dt
import json
import winreg
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from . import core

POLICY_ROOT = r"SOFTWARE\Policies\Microsoft\Windows Defender"
SCAN_KEY = POLICY_ROOT + r"\Scan"

REG_SZ = winreg.REG_SZ
REG_DWORD = winreg.REG_DWORD


@dataclass
class Setting:
    name: str          # policy 名（给人看）
    value: str         # 注册表值名
    kind: str          # dword / sz
    target: Any        # 目标值
    desc: str          # 作用说明
    risk: str          # none / low / high
    key: str = SCAN_KEY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# 平衡档：几乎不损失防护能力，只是让扫描「更温和、更少、更靠后」
# --------------------------------------------------------------------------
BALANCED: list[Setting] = [
    Setting("扫描时 CPU 使用率上限", "AvgCPULoadFactor", "dword", 5,
            "把扫描的 CPU 占用限制在 5%（Defender 允许的最低值）", "none"),
    Setting("配置计划扫描的低 CPU 优先级", "LowCpuPriority", "dword", 1,
            "计划扫描以低 CPU 优先级运行，不与你抢资源", "none"),
    Setting("仅在计算机空闲时启动计划扫描", "ScanOnlyIfIdle", "dword", 1,
            "你正在用电脑（或玩游戏）时不会突然开始扫描", "none"),
    Setting("允许用户暂停扫描", "AllowPause", "dword", 1,
            "允许随时暂停扫描，腾出资源", "none"),
    Setting("扫描网络文件", "DisableScanningNetworkFiles", "dword", 1,
            "跳过网络位置文件（本地文件仍会扫描）", "low"),
    Setting("扫描可移动驱动器", "DisableRemovableDriveScanning", "dword", 1,
            "跳过 U 盘/移动硬盘，避免慢速设备拖死全盘", "low"),
    Setting("启用重解析点扫描", "DisableReparsePointScanning", "dword", 1,
            "跳过重解析点，避免符号链接导致重复扫描", "none"),
    Setting("创建系统还原点", "DisableRestorePoint", "dword", 1,
            "扫描前不创建还原点（这一动作很慢）", "low"),
    Setting("启用电子邮件扫描", "DisableEmailScanning", "dword", 1,
            "跳过邮件文件解析", "low"),
    Setting("关闭错过扫描后的追赶扫描（快速）", "DisableCatchupQuickScan",
            "dword", 1, "错过的快速扫描不再补跑，避免突然全盘扫描", "low"),
    Setting("关闭错过扫描后的追赶扫描（完整）", "DisableCatchupFullScan",
            "dword", 1, "错过的完整扫描不再补跑，这是最常见的卡顿来源", "low"),
    Setting("运行扫描前检查最新签名", "CheckForSignaturesBeforeRunningScan",
            "dword", 0, "不在每次扫描前联网更新签名，减少启动延迟", "low"),
    Setting("快速扫描间隔（天）", "QuickScanInterval", "dword", 7,
            "每 7 天一次快速扫描（默认更频繁）", "low"),
    Setting("计划快速扫描时间", "ScheduleQuickScanTime", "dword", 720,
            "把快速扫描安排在 12:00（通常不在游戏时段）", "low"),
    Setting("扫描历史记录保留天数", "PurgeItemsAfterDelay", "dword", 30,
            "扫描记录 30 天后清理，减少历史积累", "none"),
]

# --------------------------------------------------------------------------
# 激进档：在平衡档基础上进一步关闭「耗时但不常用」的深层扫描
# --------------------------------------------------------------------------
AGGRESSIVE_EXTRA: list[Setting] = [
    Setting("扫描存档文件（压缩包）", "DisableArchiveScanning", "dword", 1,
            "不扫描压缩包内部（速度快很多，但压缩包内藏毒会漏检）", "high"),
    Setting("扫描压缩的可执行文件", "DisablePackedExeScanning", "dword", 1,
            "不扫描加壳可执行文件（速度更快，加壳木马会漏检）", "high"),
    Setting("指定扫描存档文件的最大深度", "ArchiveMaxDepth", "dword", 1,
            "若开启压缩包扫描，最多只深入 1 层", "low"),
]

PRESETS = {
    "balanced": BALANCED,
    "aggressive": BALANCED + AGGRESSIVE_EXTRA,
}

PRESET_LABEL = {
    "balanced": "平衡（推荐）",
    "aggressive": "激进（最低开销）",
    "off": "全部关闭（几乎不扫描）",
}

# --------------------------------------------------------------------------
# 「全部关闭」预设：把所有能关的「扫描」都关掉
# --------------------------------------------------------------------------
# 说明：所谓「关掉所有扫描」在策略层面能关的是这些开关。
# 实时保护本身（DisableRealtimeMonitoring）不在本工具的范围内 —— 那属于
# 关闭防护而不是减少扫描开销，且会引起用户误解，本工具不碰。
MINIMAL_EXTRA: list[Setting] = [
    Setting("扫描压缩包内的可执行文件", "DisablePackedExeScanning", "dword", 1,
            "不扫描加壳/压缩的可执行文件", "high"),
    Setting("关闭启发式扫描", "DisableHeuristics", "dword", 1,
            "关闭启发式分析（这是最费 CPU 的一步，但会显著降低检出率）", "high"),
    Setting("扫描存档文件的最大深度", "ArchiveMaxDepth", "dword", 1,
            "若仍扫描压缩包，最多只深入 1 层", "low"),
    Setting("指定要扫描的存档文件的最大大小", "ArchiveMaxSize", "dword", 1,
            "只扫描 1 KB 以内的存档（等效跳过）", "high"),
    Setting("扫描映射的网络驱动器（完整扫描）",
            "DisableScanningMappedNetworkDrivesForFullScan", "dword", 1,
            "跳过映射网络驱动器", "low"),
    Setting("配置计划扫描的低 CPU 优先级", "LowCpuPriority", "dword", 1,
            "强制低优先级，避免抢占前台", "none"),
    Setting("仅在计算机空闲时启动计划扫描", "ScanOnlyIfIdle", "dword", 1,
            "只在完全空闲时才自动扫描", "none"),
    Setting("运行扫描前检查最新签名", "CheckForSignaturesBeforeRunningScan",
            "dword", 0, "不联网更新签名", "low"),
    Setting("计划快速扫描时间间隔（天）", "QuickScanInterval", "dword", 30,
            "改为 30 天才一次快速扫描", "low"),
    Setting("指定每天运行快速扫描的时间", "ScheduleQuickScanTime", "dword", 0,
            "0 = 不指定具体时间（配合 30 天间隔）", "low"),
    Setting("关闭错过扫描后的追赶扫描（快速）", "DisableCatchupQuickScan",
            "dword", 1, "错过的快速扫描不补跑", "low"),
    Setting("关闭错过扫描后的追赶扫描（完整）", "DisableCatchupFullScan",
            "dword", 1, "错过的完整扫描不补跑", "low"),
    Setting("扫描历史记录保留天数", "PurgeItemsAfterDelay", "dword", 7,
            "历史记录 7 天后清理", "none"),
]

# 合并三个档位并按 value 去重（后出现的覆盖先出现的），
# 避免同一策略被写两次导致冲突。
_merged: dict[str, Setting] = {}
for _s in BALANCED + AGGRESSIVE_EXTRA + MINIMAL_EXTRA:
    _merged[_s.value] = _s
PRESETS["off"] = list(_merged.values())


# --------------------------------------------------------------------------
# 备份 / 应用 / 还原
# --------------------------------------------------------------------------
def backup_dir() -> Path:
    d = core.data_dir() / "defender_backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_value(key_path: str, name: str) -> tuple[bool, Any]:
    """返回 (是否存在, 值)。"""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            value, _ = winreg.QueryValueEx(k, name)
            return True, value
    except OSError:
        return False, None


def read_current() -> dict[str, Any]:
    """读取当前「扫描」页策略值。"""
    out: dict[str, Any] = {}
    keys = {SCAN_KEY}
    for s in BALANCED + AGGRESSIVE_EXTRA:
        keys.add(s.key)
    for key in sorted(keys):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                count = winreg.QueryInfoKey(k)[1]
                for i in range(count):
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    out[name] = value
        except OSError:
            continue
    return out


def key_exists(path: str = SCAN_KEY) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path):
            return True
    except OSError:
        return False


def preview(preset: str = "balanced") -> list[dict[str, Any]]:
    """列出将要发生的改动（不写入）。"""
    settings = PRESETS.get(preset, BALANCED)
    current = read_current()
    rows: list[dict[str, Any]] = []
    for s in settings:
        exists, value = _read_value(s.key, s.value)
        rows.append({
            "name": s.name,
            "value": s.value,
            "key": s.key,
            "current": value if exists else None,
            "target": s.target,
            "desc": s.desc,
            "risk": s.risk,
            "changed": (not exists) or value != s.target,
        })
    return rows


def backup() -> Path:
    """把当前策略完整备份成 JSON，返回文件路径。"""
    snapshot = {
        "time": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_key_exists": key_exists(SCAN_KEY),
        "root_key_exists": key_exists(POLICY_ROOT),
        "values": read_current(),
        "raw_scan_values": _read_all(SCAN_KEY),
    }
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = backup_dir() / f"defender_policy_{stamp}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    core.log(f"Defender 策略已备份到 {path}", source="defender")
    return path


def _read_all(key_path: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            count = winreg.QueryInfoKey(k)[1]
            for i in range(count):
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out[name] = value
    except OSError:
        pass
    return out


def list_backups() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(backup_dir().glob("defender_policy_*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"_file": str(f), "time": data.get("time", ""),
                    "count": len(data.get("values") or {})})
    return out


def _write_dword(key_path: str, name: str, value: int) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                            winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, REG_DWORD, int(value))


def _delete_value(key_path: str, name: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def is_admin() -> bool:
    return core.is_admin()


def apply_preset(preset: str = "balanced") -> dict[str, Any]:
    """应用预设。先备份，再逐项写入。"""
    if not is_admin():
        return {"ok": False, "error": "需要管理员权限", "applied": 0, "backup": ""}
    settings = PRESETS.get(preset, BALANCED)
    backup_path = backup()
    applied = 0
    failed: list[str] = []
    for s in settings:
        try:
            if s.kind == "dword":
                _write_dword(s.key, s.value, int(s.target))
            else:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, s.key, 0,
                                        winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, s.value, 0, REG_SZ, str(s.target))
            applied += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{s.name}: {exc}")
    core.log(f"应用 Defender 策略[{preset}]：成功 {applied}，失败 {len(failed)}",
             source="defender")
    core.log_event("defender_policy", {"preset": preset, "applied": applied,
                                       "failed": failed, "backup": str(backup_path)})
    return {"ok": not failed, "applied": applied, "failed": failed,
            "backup": str(backup_path), "total": len(settings)}


def restore_backup(path: str | Path) -> dict[str, Any]:
    """从备份还原。"""
    if not is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"备份文件无法读取：{exc}"}
    target_values: dict[str, Any] = snapshot.get("raw_scan_values") or {}
    current = _read_all(SCAN_KEY)
    restored = 0
    removed = 0
    for name in current:
        if name not in target_values:
            _delete_value(SCAN_KEY, name)
            removed += 1
    for name, value in target_values.items():
        try:
            if isinstance(value, int):
                _write_dword(SCAN_KEY, name, value)
            else:
                with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, SCAN_KEY, 0,
                                        winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, name, 0, REG_SZ, str(value))
            restored += 1
        except Exception as exc:  # noqa: BLE001
            core.log(f"还原 {name} 失败: {exc}", level="ERROR", source="defender")
    core.log(f"Defender 策略已还原：恢复 {restored} 项，删除 {removed} 项",
             source="defender")
    return {"ok": True, "restored": restored, "removed": removed}


def restore_defaults() -> dict[str, Any]:
    """删除本工具写入的全部策略值（回到「未配置」）。"""
    if not is_admin():
        return {"ok": False, "error": "需要管理员权限"}
    removed = 0
    for s in BALANCED + AGGRESSIVE_EXTRA:
        exists, _ = _read_value(s.key, s.value)
        if exists:
            _delete_value(s.key, s.value)
            removed += 1
    core.log(f"Defender 策略已恢复未配置：删除 {removed} 项", source="defender")
    return {"ok": True, "removed": removed}


# --------------------------------------------------------------------------
# 状态查询（含实际生效情况）
# --------------------------------------------------------------------------
def live_status() -> dict[str, Any]:
    """读取 Defender 的实际运行状态（用于界面展示）。"""
    import subprocess
    script = (
        "$c = Get-MpComputerStatus | Select-Object "
        "AMRunningMode,RealTimeProtectionEnabled,AntivirusEnabled,"
        "IsTamperProtected,QuickScanStartTime,QuickScanAge;"
        "$p = Get-MpPreference | Select-Object ScanAvgCPULoadFactor,"
        "DisableRealtimeMonitoring,DisableArchiveScanning,"
        "DisableRemovableDriveScanning,ScanOnlyIfIdleEnabled;"
        "[pscustomobject]@{status=$c;pref=$p} | ConvertTo-Json -Compress -Depth 4")
    proc = core.run_powershell(script, timeout=60)
    text = (proc.stdout or b"").decode("utf-8", "replace").strip()
    try:
        return json.loads(text)
    except ValueError:
        return {}


def tamper_protected() -> bool:
    try:
        return bool(live_status().get("status", {}).get("IsTamperProtected"))
    except Exception:  # noqa: BLE001
        return False


def notify_policy_change() -> None:
    """通知系统策略已更新（可选，加速生效）。"""
    try:
        core.run(["gpupdate", "/force", "/target:computer"], timeout=180)
    except Exception:  # noqa: BLE001
        pass
