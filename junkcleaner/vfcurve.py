"""Afterburner V/F 曲线解析与改写。

格式（逆向所得，已用本机 Profile 验证）
---------------------------------------
VFCurve 是十六进制字符串，解码后为：

    [12 字节头部]
    然后重复 N 次，每次 12 字节：
        float32  电压 (mV)      例如 450.0 / 900.0 / 1240.0
        float32  频率 (MHz)     例如 255.0 / 2100.0 / 3015.0
        float32  保留 (0.0)

头部之后、尾部之前会有一片 0 填充；尾部是风扇曲线（同样是 float 对）。

这个结构允许我们精确地：
  * 读出完整 V/F 曲线（每个电压档位对应的频率）
  * 针对某个目标频率，单独下调它所在点的电压
  * 原样写回（不改动其它字节）
"""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from . import core

HEADER_SIZE = 12
POINT_SIZE = 12

# 曲线有效性上限：超过显卡 boost 上限的点必然是坏数据。
# 实测本机 Profile 的 Startup/Profile1 段尾部有 45 个 4840MHz 的填充值，
# 必须过滤，否则"某频率对应电压"的计算会得出完全错误的结果。
MAX_PLAUSIBLE_MHZ = 3500

SECTIONS_PRIORITY = ("Defaults", "Profile1", "Startup")

# 哪个段是「完整曲线」/「实际生效曲线」
FULL_SECTION = "Defaults"      # 127 点，覆盖到 2940MHz（完整 V/F 曲线）
ACTIVE_SECTION = "Startup"     # 82 点，只覆盖到 2700MHz（实际生效的基础曲线）
AB_DIRS = [
    Path(r"D:\Program Files (x86)\MSI Afterburner"),
    Path(r"C:\Program Files (x86)\MSI Afterburner"),
    Path(r"C:\Program Files\MSI Afterburner"),
    Path(r"D:\Program Files\MSI Afterburner"),
    Path(r"E:\Program Files (x86)\MSI Afterburner"),
    Path(r"E:\Program Files\MSI Afterburner"),
]


def find_afterburner() -> Path | None:
    """自动发现 Afterburner 安装位置。

    顺序：常见路径 → 注册表 → 运行中进程 → 全盘常见根目录浅层搜索。
    """
    # 1) 常见路径
    for d in AB_DIRS:
        if (d / "MSIAfterburner.exe").exists():
            return d
    # 2) 注册表卸载项
    try:
        import winreg
        roots = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, sub in roots:
            try:
                with winreg.OpenKey(hive, sub) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            name = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, name) as k:
                                disp = str(winreg.QueryValueEx(
                                    k, "DisplayName")[0] or "")
                                if "afterburner" not in disp.lower():
                                    continue
                                loc = str(winreg.QueryValueEx(
                                    k, "InstallLocation")[0] or "")
                                if loc and (
                                        Path(loc) / "MSIAfterburner.exe").exists():
                                    return Path(loc)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    # 3) 运行中的进程
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "msiafterburner.exe":
                exe = p.info.get("exe") or ""
                if exe:
                    return Path(exe).parent
    except Exception:  # noqa: BLE001
        pass
    # 4) 常见根目录浅层搜索
    for root in (r"C:\Program Files", r"C:\Program Files (x86)",
                 r"D:\Program Files", r"D:\Program Files (x86)",
                 r"E:\Program Files", r"E:\Program Files (x86)"):
        try:
            for d in Path(root).iterdir():
                if "afterburner" in d.name.lower() and (
                        d / "MSIAfterburner.exe").exists():
                    return d
        except OSError:
            continue
    return None


def afterburner_dir() -> Path | None:
    return find_afterburner()


def profiles_dir() -> Path | None:
    d = afterburner_dir()
    return (d / "Profiles") if d else None


def afterburner_config() -> Path | None:
    """Afterburner 的全局配置文件（MSIAfterburner.cfg）。"""
    d = afterburner_dir()
    return (d / "MSIAfterburner.cfg") if d else None


def find_gpu_profile() -> Path | None:
    """找到当前 NVIDIA 显卡对应的 Profile 文件。"""
    pdir = profiles_dir()
    if not pdir or not pdir.exists():
        return None
    best: tuple[int, Path] | None = None
    for f in pdir.glob("VEN_10DE*.cfg"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "VFCurve=" not in text:
            continue
        score = len(text)
        if best is None or score > best[0]:
            best = (score, f)
    return best[1] if best else None


@dataclass
class VfPoint:
    index: int
    voltage_mv: float
    freq_mhz: float
    byte_offset: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VfCurve:
    """一条 V/F 曲线的可读写视图（保留原始字节，只改动指定点）。"""

    def __init__(self, raw: bytes) -> None:
        self.raw = bytearray(raw)
        self.points: list[VfPoint] = []
        self._parse()

    def _parse(self) -> None:
        data = self.raw
        pos = HEADER_SIZE
        idx = 0
        # 解析到出现 0 电压或越界为止
        while pos + POINT_SIZE <= len(data):
            volt = struct.unpack_from("<f", data, pos)[0]
            freq = struct.unpack_from("<f", data, pos + 4)[0]
            if volt != volt or volt <= 0.0 or volt > 2000.0:
                break
            if freq != freq or freq < 0.0 or freq > 5000.0:
                break
            # 过滤坏点：超过实际上限的频率是填充数据，不是有效曲线
            if freq > MAX_PLAUSIBLE_MHZ:
                idx += 1
                pos += POINT_SIZE
                continue
            self.points.append(VfPoint(idx, volt, freq, pos))
            idx += 1
            pos += POINT_SIZE

    # ---------------- 查询 ----------------
    def to_list(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.points]

    def nearest_to_freq(self, freq_mhz: float) -> VfPoint | None:
        if not self.points:
            return None
        return min(self.points, key=lambda p: abs(p.freq_mhz - freq_mhz))

    def points_near_freq(self, freq_mhz: float, window: float = 60.0
                         ) -> list[VfPoint]:
        got = [p for p in self.points if abs(p.freq_mhz - freq_mhz) <= window]
        return sorted(got, key=lambda p: p.freq_mhz)

    def voltage_for_freq(self, freq_mhz: float) -> float | None:
        p = self.nearest_to_freq(freq_mhz)
        return p.voltage_mv if p else None

    @property
    def max_freq(self) -> float:
        return max((p.freq_mhz for p in self.points), default=0.0)

    @property
    def max_voltage(self) -> float:
        return max((p.voltage_mv for p in self.points), default=0.0)

    # ---------------- 修改 ----------------
    def set_voltage(self, index: int, mv: float) -> bool:
        """把第 index 个点的电压改为 mv（只改这 4 字节）。"""
        if not (0 <= index < len(self.points)):
            return False
        p = self.points[index]
        struct.pack_into("<f", self.raw, p.byte_offset, float(mv))
        p.voltage_mv = float(mv)
        return True

    def set_frequency(self, index: int, mhz: float) -> bool:
        """把第 index 个点的频率改为 mhz（只改这 4 字节）。"""
        if not (0 <= index < len(self.points)):
            return False
        p = self.points[index]
        struct.pack_into("<f", self.raw, p.byte_offset + 4, float(mhz))
        p.freq_mhz = float(mhz)
        return True

    def lock_frequency(self, freq_mhz: float, voltage_mv: float
                       ) -> dict[str, Any]:
        """把曲线锁成「目标电压 → 目标频率」的平台。

        这是 Afterburner 曲线编辑里最常用、也最能稳定复现的做法：
          1. 找到电压最接近 voltage_mv 的点作为平台起点（锚点）；
          2. 把锚点设为 (voltage_mv, freq_mhz)；
          3. 把所有「电压不低于锚点」的点频率统一为 freq_mhz。

        这样 GPU 在重载时会沿着曲线爬升，到锚点后频率不再上涨，
        驱动会停在「能提供目标频率的最低电压」= 锚点电压上。
        低电压段保持原样，所以待机/轻载仍然会自然降到低频。
        """
        if not self.points:
            return {"ok": False, "error": "曲线为空"}
        target_f = float(freq_mhz)
        target_v = float(voltage_mv)
        anchor = min(self.points, key=lambda p: abs(p.voltage_mv - target_v))
        changed: list[dict[str, Any]] = []
        for p in self.points:
            if p.voltage_mv + 1e-3 < anchor.voltage_mv:
                continue                      # 低电压段保留原始降频行为
            if abs(p.freq_mhz - target_f) > 1e-3:
                before = p.freq_mhz
                if self.set_frequency(p.index, target_f):
                    changed.append({"index": p.index, "before_mhz": before,
                                    "voltage_mv": p.voltage_mv})
        old_anchor_v = anchor.voltage_mv
        if abs(old_anchor_v - target_v) > 1e-3:
            self.set_voltage(anchor.index, target_v)
        return {"ok": True, "anchor_index": anchor.index,
                "anchor_voltage_mv": target_v,
                "target_freq_mhz": target_f,
                "changed": changed}

    def apply_flat_voltage_near(self, freq_mhz: float, mv: float,
                                window: float = 60.0) -> list[int]:
        """把目标频率附近的一小段点统一压到 mv，返回改动的点序号。

        取一小段（而不是单点）是为了形成平坦的「锁定电压运行」区间，
        这正是 Afterburner 里 Ctrl+F 曲线拉平的等效做法。
        """
        changed: list[int] = []
        for p in self.points_near_freq(freq_mhz, window):
            if mv < p.voltage_mv:              # 只降压，不升压
                self.set_voltage(p.index, mv)
                changed.append(p.index)
        return changed

    def to_hex(self) -> str:
        return bytes(self.raw).hex().upper()

    def diff_bytes(self, other: bytes) -> int:
        return sum(1 for a, b in zip(self.raw, other) if a != b)


# --------------------------------------------------------------------------
# 读写 Profile
# --------------------------------------------------------------------------
def _section_span(text: str, section: str) -> tuple[int, int] | None:
    m = re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.M)
    if not m:
        return None
    start = m.end()
    nxt = re.search(r"^\[.+?\]\s*$", text[start:], re.M)
    end = start + (nxt.start() if nxt else len(text) - start)
    return start, end


def read_core_boost(profile: Path, section: str = "Startup") -> int | None:
    """读取 CoreClkBoost（核心频率偏移补偿值）。

    这个值不是 V/F 曲线的一部分，但会整体平移核心时钟。实测：
      CoreClkBoost = -502296  -> 满载被压到 2325MHz
      CoreClkBoost = 0        -> 同曲线跑到 2835MHz
    只改 VFCurve 而不同步它，就会出现“曲线写对了但频率上不去”。
    """
    try:
        text = profile.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    span = _section_span(text, section)
    if span is None:
        return None
    m = re.search(r"^CoreClkBoost\s*=\s*(-?\d+)",
                  text[span[0]:span[1]], re.M)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def clear_core_boost(profile: Path,
                     sections: list[str] | None = None) -> int:
    """把 CoreClkBoost 归零，返回改动段数。

    锁定 V/F 曲线时必须同时做这一步，否则历史遗留的负偏移会继续
    把实际频率压低。只影响频率偏移字段，不动电压与其它设置。
    """
    sections = sections or ["Startup", "Profile1"]
    text = profile.read_text(encoding="utf-8-sig", errors="replace")
    changed = 0
    for sec in sections:
        span = _section_span(text, sec)
        if span is None:
            continue
        body = text[span[0]:span[1]]
        new_body, n = re.subn(r"^(CoreClkBoost\s*=\s*)-?\d+",
                              r"\g<1>0", body, count=1, flags=re.M)
        if n:
            text = text[:span[0]] + new_body + text[span[1]:]
            changed += n
    if changed:
        profile.write_text(text, encoding="utf-8")
        core.log(f"已归零 CoreClkBoost（{changed} 个段），解除核心频率偏移",
                 source="vfcurve")
    return changed


def read_curve(profile: Path, section: str = "Startup") -> VfCurve | None:
    text = profile.read_text(encoding="utf-8", errors="replace")
    span = _section_span(text, section)
    if span is None:
        return None
    m = re.search(r"VFCurve=([0-9A-Fa-f]+)", text[span[0]:span[1]])
    if not m:
        return None
    try:
        return VfCurve(bytes.fromhex(m.group(1)))
    except ValueError:
        return None


def read_best_curve(profile: Path | None = None,
                    gpu_max_mhz: int = 0) -> tuple[VfCurve | None, str]:
    """按优先级读取最可信的曲线段。

    实测：Startup / Profile1 段尾部可能有大量坏点（本机是 45 个 4840MHz），
    而 Defaults 段是干净的完整曲线。所以优先读 Defaults，
    并用「坏点最少」作为最终判据。

    返回 (曲线, 使用的段名)。
    """
    profile = profile or find_gpu_profile()
    if profile is None:
        return None, ""
    limit = gpu_max_mhz or MAX_PLAUSIBLE_MHZ
    best: tuple[int, int, VfCurve, str] | None = None
    for sec in SECTIONS_PRIORITY:
        c = read_curve(profile, sec)
        if c is None or not c.points:
            continue
        # 坏点计数（用实际显卡上限，而不是硬编码）
        bad = sum(1 for p in c.points if p.freq_mhz > limit * 1.05)
        # 评分：坏点少优先，其次点数多
        score = (-bad, len(c.points))
        if best is None or score > best[:2]:
            best = (score[0], score[1], c, sec)
    if best is None:
        return None, ""
    return best[2], best[3]


def read_base_curve(profile: Path | None = None) -> tuple[VfCurve | None, str]:
    """读取「用于重新计算锁定曲线」的干净基准。

    Defaults 是 Afterburner 保存的出厂曲线，不会被用户编辑改动，
    因此每次锁定都从它出发，避免在已经压平的曲线上反复操作导致误差累积。
    若没有 Defaults，再从最早的备份里找一条含 Defaults 的原始曲线，
    最后才退回当前可用的曲线。
    """
    profile = profile or find_gpu_profile()
    if profile is None:
        return None, ""
    c = read_curve(profile, "Defaults")
    if c is not None and c.points:
        return c, "Defaults"
    # 从备份里找 Defaults，避免把已经锁定的 Startup/Profile 当作基准
    d = core.data_dir() / "afterburner_backups"
    if d.exists():
        for bak in sorted(d.glob("*.cfg")):
            bc = read_curve(bak, "Defaults")
            if bc is not None and bc.points:
                return bc, f"backup:{bak.name}"
    return read_best_curve(profile)


def profile_slots(profile: Path | None = None) -> list[str]:
    """列出 Profile 文件里实际存在的 Profile 段（Profile1..Profile10）。"""
    profile = profile or find_gpu_profile()
    if profile is None:
        return []
    try:
        text = profile.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    slots = re.findall(r"^\[(Profile\d+)\]\s*$", text, re.M)
    if not slots:
        # 有些版本用 [Profile 1] 或 [Profile1] 之外的写法，宽松兜底
        slots = re.findall(r"^\[(Profile[\s_-]*\d+)\]\s*$", text, re.M)
    return sorted(dict.fromkeys(slots),
                  key=lambda s: int(re.search(r"\d+", s).group(0)))


def _ini_get(text: str, key: str, section: str = "Settings") -> str:
    span = _section_span(text, section)
    if span is None:
        m = re.search(rf"^{re.escape(key)}\s*=\s*(.*)$", text, re.M)
        return m.group(1).strip() if m else ""
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.*)$",
                  text[span[0]:span[1]], re.M)
    return m.group(1).strip() if m else ""


def _ini_set(text: str, key: str, value: str,
             section: str = "Settings") -> tuple[str, bool]:
    """在指定 INI 段内设置键值；不存在则追加。返回 (新文本, 是否改动)。"""
    span = _section_span(text, section)
    if span is None:
        # 文件可能没有 [Settings] 段，直接在文件末尾追加一个段
        if re.search(rf"^{re.escape(key)}\s*=", text, re.M):
            new_text, n = re.subn(rf"^{re.escape(key)}\s*=.*$",
                                  f"{key}={value}", text, count=1, flags=re.M)
            return new_text, bool(n)
        sep = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{sep}[{section}]\n{key}={value}\n", True
    body = text[span[0]:span[1]]
    m = re.search(rf"^{re.escape(key)}\s*=\s*(.*)$", body, re.M)
    if m and m.group(1).strip() == str(value):
        return text, True   # 值已是目标值，视为已就绪
    new_body, n = re.subn(rf"^{re.escape(key)}\s*=.*$",
                          f"{key}={value}", body, count=1, flags=re.M)
    if n == 0:
        add = f"{key}={value}\n"
        new_body = body + add
    if new_body == body:
        return text, False
    return text[:span[0]] + new_body + text[span[1]:], True


def set_startup_profile(profile_index: int,
                        config: Path | None = None) -> dict[str, Any]:
    """设置 Afterburner 启动时自动应用的 Profile 编号。

    这些键属于全局配置 MSIAfterburner.cfg 的 [Settings] 段，不是显卡
    的 VEN_10DE*.cfg。Afterburner 各版本的键名可能不同（StartupProfile /
    StartupProfileIndex / ProfileOnStartup 等），因此这里采用“只改配置文件
    中已存在的候选键，不存在才追加标准键”的策略，避免拍脑袋写错键名。
    """
    config = config or afterburner_config()
    if config is None or not config.exists():
        return {"ok": False, "error": "未找到 MSIAfterburner.cfg"}
    try:
        text = config.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    changed = False
    # 启动预设：优先改已有候选键；一个都没有才追加最常见的标准键
    preset_keys = ("StartupProfile", "StartupProfileIndex",
                   "ProfileOnStartup", "StartupProfileNumber")
    for key in preset_keys:
        if re.search(rf"^{re.escape(key)}\s*=", text, re.M):
            text, n = _ini_set(text, key, str(int(profile_index)))
            changed = changed or n
            break
    else:
        text, n = _ini_set(text, "StartupProfile", str(int(profile_index)))
        changed = changed or n
    # 这些开关保证“开机自启 + 低层访问”，只改已存在的键，避免污染
    for key, value in (("StartWithWindows", "1"),
                       ("StartMinimized", "1"),
                       ("LowLevelIO", "1"),
                       ("UnlockVoltageControl", "1"),
                       ("UnlockVoltageMonitoring", "1")):
        if re.search(rf"^{re.escape(key)}\s*=", text, re.M):
            text, n = _ini_set(text, key, value)
            changed = changed or n
    if not changed:
        return {"ok": False, "error": "未能写入 Afterburner 启动配置"}
    # 原文件可能带 BOM，保留编码兼容性
    config.write_text(text.lstrip("\ufeff"), encoding="utf-8")
    core.log(f"Afterburner 启动预设已设为 Profile {profile_index}",
             source="vfcurve")
    return {"ok": True, "config": str(config),
            "startup_profile": int(profile_index)}


def get_startup_profile(config: Path | None = None) -> int:
    config = config or afterburner_config()
    if config is None or not config.exists():
        return -1
    try:
        text = config.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return -1
    for key in ("StartupProfile", "StartupProfileIndex",
                "ProfileOnStartup", "StartupProfileNumber"):
        v = _ini_get(text, key)
        if v:
            try:
                return int(v)
            except ValueError:
                return -1
    return -1


def write_locked_profile(profile: Path, curve: VfCurve,
                         section: str = "Profile1",
                         make_startup: bool = True) -> dict[str, Any]:
    """把一条锁定曲线写入指定 Profile 段，并可选设为启动预设。

    与 write_curve 的区别：write_curve 用于搜索过程中的临时应用，
    本函数用于生成最终预设；会同时写入 Startup 与目标 Profile 段，
    让 Afterburner 手动应用与开机自动应用拿到同一份曲线。
    Defaults 始终保持出厂基准，绝不覆盖。
    """
    if not curve.points:
        return {"ok": False, "error": "曲线为空"}
    slots = profile_slots(profile)
    if section not in slots:
        return {"ok": False, "error": f"Profile 文件中不存在 [{section}]"}
    r = write_curve(profile, curve, sections=["Startup", section])
    if not r.get("ok"):
        return r
    out: dict[str, Any] = {"ok": True, "section": section,
                           "written": r.get("sections")}
    if make_startup:
        # Afterburner 的 StartupProfile 是 1-based 的 Profile 编号。
        idx_m = re.search(r"(\d+)", section)
        idx = int(idx_m.group(1)) if idx_m else 1
        s = set_startup_profile(idx)
        out["startup"] = s
        if not s.get("ok"):
            out["ok"] = False
            out["error"] = s.get("error")
    return out


def backup_profile(profile: Path) -> Path:
    d = core.data_dir() / "afterburner_backups"
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = d / f"{profile.stem}_{stamp}.cfg"
    shutil.copy2(profile, dst)
    core.log(f"Afterburner Profile 已备份到 {dst}", source="vfcurve")
    return dst


def write_curve(profile: Path, curve: VfCurve, sections: list[str] | None = None
                ) -> dict[str, Any]:
    """把曲线写回指定 section（默认同时写 Startup 和 Profile1）。"""
    sections = sections or ["Startup", "Profile1"]
    text = profile.read_text(encoding="utf-8", errors="replace")
    new_hex = curve.to_hex()
    changed = 0
    for sec in sections:
        span = _section_span(text, sec)
        if span is None:
            continue
        body = text[span[0]:span[1]]
        new_body, n = re.subn(r"VFCurve=[0-9A-Fa-f]+", f"VFCurve={new_hex}",
                              body, count=1)
        if n:
            text = text[:span[0]] + new_body + text[span[1]:]
            changed += n
    if not changed:
        return {"ok": False, "error": "未找到可写入的 VFCurve 段"}
    profile.write_text(text, encoding="utf-8")
    core.log(f"已写入 V/F 曲线（{changed} 个段）到 {profile.name}", source="vfcurve")
    return {"ok": True, "sections": changed, "profile": str(profile)}


def restore_profile(backup: Path, target: Path) -> dict[str, Any]:
    if not backup.exists():
        return {"ok": False, "error": "备份不存在"}
    shutil.copy2(backup, target)
    core.log(f"已从备份还原 {target.name}", source="vfcurve")
    return {"ok": True, "restored": str(target)}


def list_backups() -> list[dict[str, Any]]:
    d = core.data_dir() / "afterburner_backups"
    out: list[dict[str, Any]] = []
    if not d.exists():
        return out
    for f in sorted(d.glob("*.cfg"), reverse=True):
        out.append({"_file": str(f), "name": f.name,
                    "size": f.stat().st_size,
                    "time": time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(f.stat().st_mtime))})
    return out


# --------------------------------------------------------------------------
# 让 Afterburner 重新加载配置
# --------------------------------------------------------------------------
def afterburner_path() -> str:
    d = afterburner_dir()
    return str(d / "MSIAfterburner.exe") if d else ""


def is_running() -> bool:
    try:
        import psutil
        return any(p.info["name"].lower() == "msiafterburner.exe"
                   for p in psutil.process_iter(["name"]))
    except Exception:  # noqa: BLE001
        return False


def running_pids() -> list[int]:
    """返回正在运行的 Afterburner 主进程 PID 列表。"""
    out: list[int] = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            if (p.info.get("name") or "").lower() == "msiafterburner.exe":
                out.append(int(p.info["pid"]))
    except Exception:  # noqa: BLE001
        pass
    return out


def stop_afterburner(wait: float = 6.0) -> dict[str, Any]:
    """关闭 Afterburner 主进程（不动 RTSS）。

    为什么必须关：Afterburner 运行时不会重新读取被外部修改的 Profile 文件，
    它会用内存里的旧预设覆盖回去。所以「写曲线 -> 应用」必须走
    「先退出 -> 写文件 -> 再启动」这条路，否则电压写了也不生效。
    """
    pids = running_pids()
    if not pids:
        return {"ok": True, "stopped": 0}
    try:
        import psutil
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except Exception:  # noqa: BLE001
                pass
        end = time.time() + wait
        while time.time() < end and running_pids():
            time.sleep(0.3)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    left = running_pids()
    core.log(f"已关闭 Afterburner（{len(pids)} 个进程），剩余 {len(left)}",
             source="vfcurve")
    return {"ok": not left, "stopped": len(pids), "remaining": len(left)}


def reload_profile(profile_index: int = 1) -> dict[str, Any]:
    """让 Afterburner 应用指定 Profile（它会自己读回 cfg）。

    Afterburner 的命令行开关是 -Profile1 / -Profile2 / …，
    不是 -Profile 1。旧实现写成后者，实际上没有选中目标预设，
    这也是「写入了曲线但频率不生效」的原因之一。
    """
    exe = afterburner_path()
    if not exe:
        return {"ok": False, "error": "未找到 MSIAfterburner.exe"}
    idx = max(1, int(profile_index))
    switch = f"-Profile{idx}"
    if not is_running():
        try:
            subprocess.Popen([exe, switch], cwd=str(Path(exe).parent))
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "detail": f"已启动 Afterburner 并应用 {switch}"}
    proc = core.run([exe, switch], timeout=30)
    return {"ok": True, "detail": f"{switch} rc={proc.returncode}"}
