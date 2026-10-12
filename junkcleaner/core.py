"""共享基础层：路径、权限、配置、日志、注册表/进程工具。"""

from __future__ import annotations

import ctypes
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "JunkCleaner"


def _boot(msg: str) -> None:
    """启动诊断日志。仅当设置环境变量 JUNKCLEANER_DEBUG 时才写。"""
    if not os.environ.get("JUNKCLEANER_DEBUG"):
        return
    try:
        import datetime as _d
        import sys as _s
        base = os.path.dirname(_s.executable) if getattr(_s, "frozen", False) \
            else os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "startup.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{_d.datetime.now():%H:%M:%S}\t{msg}\n")
    except Exception:  # noqa: BLE001
        pass

# Windows 无控制台窗口标志
CREATE_NO_WINDOW = 0x08000000


# --------------------------------------------------------------------------
# 路径
# --------------------------------------------------------------------------
def _program_data() -> Path:
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base)


def data_dir() -> Path:
    """数据目录，优先 ProgramData，无写权限时回退到 LocalAppData。"""
    override = os.environ.get("JUNKCLEANER_DATA")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(_program_data() / APP_NAME)
    candidates.append(Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME)
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            probe = c / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return c
        except OSError:
            continue
    return Path.cwd() / APP_NAME


def quarantine_dir() -> Path:
    """隔离区目录。

    默认沿用数据目录，但允许用户在界面上改成其它盘/文件夹，
    避免默认全落在 C 盘。配置项 quarantine_dir 为空时用默认值。
    """
    custom = str(load_config().get("quarantine_dir") or "").strip()
    if custom:
        try:
            d = Path(custom)
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return d
        except OSError:
            # 自定义目录不可用（盘符不存在/无权限）时回退默认，
            # 不要让清理/拦截因为一个坏配置直接失败。
            log(f"隔离区目录不可用，回退默认：{custom}", level="WARN",
                source="core")
    d = data_dir() / "quarantine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_quarantine_dir() -> Path:
    """默认隔离区目录（不受用户配置影响）。"""
    d = data_dir() / "quarantine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def status_path() -> Path:
    return data_dir() / "status.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "guard_enabled": False,
    "guard_interval": 1.0,
    "auto_quarantine_installer": True,
    # 隔离区目录：为空时使用默认（%ProgramData%\JunkCleaner\quarantine）
    "quarantine_dir": "",
    "block_known_installs": True,
    "disabled_signature_ids": [],     # 用户手动取消拦截的家族
    "custom_block_names": [],         # 用户自定义拦截的可执行文件名
    "guard_ignore_names": [],         # 忽略名单：命中即无条件放行
    "uninstall_after_scan": False,
    "show_disputed": True,
    "min_severity": "disputed",
    "last_scan": None,
    # 资源占用
    "scan_intensity": "low",        # low / medium / high（默认低占用）
    "low_priority_scan": True,      # 扫描时降低进程优先级
    # 内存
    "auto_release": False,
    "auto_threshold": 85,           # 内存占用超过该百分比时自动释放
    "auto_interval": 300,           # 两次自动释放的最小间隔（秒）
    "auto_level": "standard",       # gentle / standard / deep
}


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    tmp = config_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config_path())


def update_config(**changes: Any) -> dict[str, Any]:
    cfg = load_config()
    cfg.update(changes)
    save_config(cfg)
    return cfg


# --------------------------------------------------------------------------
# 权限 / 进程
# --------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin(argv: list[str] | None = None) -> bool:
    """以管理员身份重启当前程序（UAC 提权）。"""
    if is_admin():
        return True
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = subprocess.list2cmdline(argv or sys.argv[1:])
    else:
        exe = sys.executable
        params = subprocess.list2cmdline([str(Path(__file__).resolve().parents[1] / "junkcleaner_entry.py"),
                                          *(argv or sys.argv[1:])])
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return rc > 32
    except Exception:  # noqa: BLE001
        return False


def python_exe_windowless() -> str:
    """返回用于后台守护的 pythonw.exe（不存在则退回当前解释器）。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


# --------------------------------------------------------------------------
# 资源占用控制：扫描时降低优先级，避免影响前台工作与游戏
# --------------------------------------------------------------------------
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020


def set_low_priority() -> bool:
    """把当前进程降为「低于正常」，扫描/清理时减少对前台的影响。"""
    try:
        return bool(ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(),
            BELOW_NORMAL_PRIORITY_CLASS))
    except Exception:  # noqa: BLE001
        return False


def restore_priority() -> bool:
    try:
        return bool(ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(), NORMAL_PRIORITY_CLASS))
    except Exception:  # noqa: BLE001
        return False


def set_io_priority(low: bool = True) -> bool:
    """设置进程 I/O 优先级（Low=0, Normal=1, High=2）。"""
    try:
        return bool(ctypes.windll.kernel32.SetPriorityClass(
            ctypes.windll.kernel32.GetCurrentProcess(),
            BELOW_NORMAL_PRIORITY_CLASS if low else NORMAL_PRIORITY_CLASS))
    except Exception:  # noqa: BLE001
        return False


class Throttle:
    """按强度限制扫描节奏：让出 CPU 并限制读盘速率。

    MAX_RATE 常量上限：即使配置成 low，也不会低于这些值，避免扫描慢到不可用。
    """

    PROFILES = {
        # batch: 每处理多少项让出一次；pause: 让出多久(s)
        # read_bytes: 每次让出前最多读多少字节；size_timeout: 单目录体积估算上限
        "low": {"batch": 6, "pause": 0.060, "size_timeout": 0.5,
                "deep_dirs": 1, "read_bytes": 1 << 20},
        "medium": {"batch": 40, "pause": 0.02, "size_timeout": 1.5,
                   "deep_dirs": 2, "read_bytes": 8 << 20},
        "high": {"batch": 400, "pause": 0.0, "size_timeout": 4.0,
                 "deep_dirs": 2, "read_bytes": 64 << 20},
    }

    # 允许的最小间隔（保证不会慢到不可用）
    MIN_PAUSE = 0.030

    # 各档位的「自身 CPU 目标」（占单核百分比，100 = 占满一个核）
    # 相对整机 16 核：6 ≈ 0.4%，24 ≈ 1.5%，转成整机百分比都很低
    # 目标是「占单核百分比」：12 ≈ 整机 0.75%（16 核），30 ≈ 1.9%
    CPU_TARGET = {"low": 12.0, "medium": 30.0, "high": 0.0}
    # 允许的突发额度（CPU 秒），用于吸收启动瞬间的尖峰
    CPU_BURST = 0.015

    def __init__(self, intensity: str = "medium") -> None:
        profile = self.PROFILES.get(intensity) or self.PROFILES["medium"]
        self.intensity = intensity
        self.batch = int(profile["batch"])
        self.pause = float(profile["pause"])
        self.size_timeout = float(profile["size_timeout"])
        self.deep_dirs = int(profile["deep_dirs"])
        self.read_budget = int(profile["read_bytes"])
        self._count = 0
        self._bytes_since_pause = 0
        self.cpu_target = self.CPU_TARGET.get(intensity, 40.0)
        self._proc = None
        self._last_cpu_time = 0.0
        self._last_wall = 0.0
        self._usage = 0.0
        self._pid = os.getpid()
        self._t0 = time.perf_counter()
        self._cpu0 = 0.0
        self._have_base = False
        # 预热基线，避免扫描刚开始的第一波突发拉高 P95
        self._sample_cpu()

    def tick(self) -> None:
        """每处理一项调用：达到批次、或自身 CPU 超过目标时让出。"""
        self._count += 1
        due = self.batch and self._count % self.batch == 0
        if not due and self.cpu_target > 0:
            due = self._over_budget()
        if due:
            self._pause()

    def add_bytes(self, n: int) -> None:
        """登记本次读取字节数；累计超过预算就让出，限制读盘速率。"""
        self._bytes_since_pause += max(0, int(n))
        if self._bytes_since_pause >= self.read_budget:
            self._bytes_since_pause = 0
            self._pause()

    def _pause(self) -> None:
        if self.pause <= 0:
            time.sleep(0)
            return
        # 令牌桶：超出目标越多，停得越久，直到回到预算内
        extra = self._overdraft()
        if extra > 0 and self.cpu_target > 0:
            fraction = self.cpu_target / 100.0
            need = min(0.6, extra / max(0.01, fraction))
            time.sleep(max(self.pause, need))
        else:
            time.sleep(self.pause)

    def _sample_cpu(self) -> tuple[float, float]:
        """返回（累计 CPU 秒, 距离开始的秒数）。"""
        now = time.perf_counter()
        if self._proc is None:
            try:
                import psutil
                self._proc = psutil.Process(self._pid)
            except Exception:  # noqa: BLE001
                self.cpu_target = 0.0
                return 0.0, 0.0
        try:
            times = self._proc.cpu_times()
            cpu = times.user + times.system
        except Exception:  # noqa: BLE001
            return 0.0, 0.0
        if not self._have_base:
            self._cpu0 = cpu
            self._t0 = now
            self._have_base = True
            return 0.0, 0.0
        used = cpu - self._cpu0
        elapsed = now - self._t0
        if elapsed > 0.05:
            self._usage = used / elapsed * 100.0
        return used, elapsed

    def _overdraft(self) -> float:
        """返回超出预算的 CPU 秒数（<=0 表示仍在预算内）。"""
        if self.cpu_target <= 0:
            return 0.0
        used, elapsed = self._sample_cpu()
        if elapsed <= 0:
            return 0.0
        allowed = (self.cpu_target / 100.0) * elapsed + self.CPU_BURST
        return used - allowed

    def _over_budget(self) -> bool:
        return self._overdraft() > 0


def scan_intensity() -> str:
    return str(load_config().get("scan_intensity", "medium") or "medium")


def run(cmd: str | list[str], timeout: int = 120, capture: bool = True) -> subprocess.CompletedProcess:
    """无窗口运行命令。cmd 为字符串时按原样交给 CreateProcess。"""
    kwargs: dict[str, Any] = dict(stdout=subprocess.PIPE if capture else None,
                                  stderr=subprocess.STDOUT if capture else None,
                                  stdin=subprocess.DEVNULL, shell=False)
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, timeout=timeout, **kwargs)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, b"[timeout]" if capture else None)


def run_powershell(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    # 先固定 UTF-8 输出，避免中文服务名/任务名乱码
    prefix = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
              "$OutputEncoding=[System.Text.Encoding]::UTF8;")
    return run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", prefix + script], timeout=timeout)


def open_folder(path: Path | str) -> None:
    try:
        os.startfile(str(path))  # noqa: S606 - 打开资源管理器属预期行为
    except OSError:
        pass


# --------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------
_log_lock = threading.Lock()


def log(message: str, level: str = "INFO", source: str = "app") -> None:
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}\t{level}\t{source}\t{message}\n"
    with _log_lock:
        try:
            day = _dt.datetime.now().strftime("%Y%m%d")
            with (logs_dir() / f"{day}.log").open("a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass
    if os.environ.get("JUNKCLEANER_VERBOSE"):
        try:
            print(line, end="")
        except Exception:  # noqa: BLE001
            pass


def read_recent_logs(limit: int = 400) -> list[str]:
    out: list[str] = []
    try:
        files = sorted(logs_dir().glob("*.log"), reverse=True)
    except OSError:
        return out
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        out.extend(reversed(lines))
        if len(out) >= limit:
            break
    return list(reversed(out[:limit]))


def log_event(kind: str, payload: dict[str, Any]) -> None:
    """结构化事件流，供「拦截记录」页展示。"""
    payload = dict(payload)
    payload["time"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["kind"] = kind
    try:
        with (data_dir() / "events.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_events(limit: int = 300) -> list[dict[str, Any]]:
    path = data_dir() / "events.jsonl"
    out: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def write_status(**fields: Any) -> None:
    cfg = {}
    try:
        cfg = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    cfg.update(fields)
    cfg["updated"] = time.time()
    try:
        status_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def read_status() -> dict[str, Any]:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------
# 注册表 / 体积工具
# --------------------------------------------------------------------------
UNINSTALL_HIVES = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
     "HKLM64"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
     "HKLM32"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
     "HKCU"),
]


def iter_uninstall_entries() -> Iterable[dict[str, Any]]:
    """遍历三处卸载注册表，产出统一结构。"""
    for hive, subkey, label in UNINSTALL_HIVES:
        try:
            with winreg.OpenKey(hive, subkey) as root:
                count = winreg.QueryInfoKey(root)[0]
                for i in range(count):
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, name) as k:
                            def gv(field: str) -> str:
                                try:
                                    value, _ = winreg.QueryValueEx(k, field)
                                    return str(value) if value is not None else ""
                                except OSError:
                                    return ""

                            entry = {
                                "key_name": name,
                                "hive": label,
                                "subkey": f"{subkey}\\{name}",
                                "display_name": gv("DisplayName"),
                                "publisher": gv("Publisher"),
                                "version": gv("DisplayVersion"),
                                "install_location": gv("InstallLocation"),
                                "uninstall_string": gv("UninstallString"),
                                "quiet_uninstall": gv("QuietUninstallString"),
                                "icon": gv("DisplayIcon"),
                                "estimated_size_kb": 0,
                            }
                            try:
                                raw_size, _ = winreg.QueryValueEx(k, "EstimatedSize")
                                entry["estimated_size_kb"] = int(raw_size)
                            except (OSError, TypeError, ValueError):
                                pass
                            entry["install_date"] = gv("InstallDate")
                    except OSError:
                        continue
                    if entry["display_name"]:
                        yield entry
        except OSError:
            continue


def delete_registry_key(hive: int, subkey: str) -> bool:
    try:
        winreg.DeleteKey(hive, subkey)
        return True
    except OSError:
        # 可能含子键，递归删除
        try:
            run_powershell(
                f"Remove-Item -LiteralPath 'Registry::{_hive_root(hive)}\\{subkey}' "
                f"-Recurse -Force -ErrorAction SilentlyContinue")
            return True
        except Exception:  # noqa: BLE001
            return False


def _hive_root(hive: int) -> str:
    return {
        winreg.HKEY_LOCAL_MACHINE: "HKEY_LOCAL_MACHINE",
        winreg.HKEY_CURRENT_USER: "HKEY_CURRENT_USER",
        winreg.HKEY_CLASSES_ROOT: "HKEY_CLASSES_ROOT",
    }.get(hive, "HKEY_LOCAL_MACHINE")


def hive_constant(label: str) -> int:
    return {"HKLM64": winreg.HKEY_LOCAL_MACHINE,
            "HKLM32": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER}.get(label, winreg.HKEY_LOCAL_MACHINE)


def path_size(path: Path, cap_seconds: float = 6.0,
              on_read: Any = None, budget: int = 0) -> int:
    """估算目录体积，超时或出错即返回已统计值。

    on_read(n)  每读一个文件条目时回调，用于限速让出；
    budget      每累计多少字节调用一次 on_read（0 表示不回调）。
    """
    total = 0
    since = 0
    deadline = time.time() + cap_seconds
    try:
        stack = [path]
        while stack:
            if time.time() > deadline:
                break
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                size = entry.stat(follow_symlinks=False).st_size
                                total += size
                                if on_read and budget:
                                    since += size
                                    if since >= budget:
                                        since = 0
                                        try:
                                            on_read()
                                        except Exception:  # noqa: BLE001
                                            pass
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return total


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0 or unit == "TB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def safe_move(src: Path, dest: Path) -> tuple[bool, str]:
    """移动到隔离区（跨盘回退为复制+删除）。"""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def safe_delete(path: Path) -> tuple[bool, str]:
    try:
        if path.is_dir():
            run_powershell(
                f"Remove-Item -LiteralPath {json.dumps(str(path))} -Recurse -Force "
                f"-ErrorAction SilentlyContinue")
        else:
            path.unlink(missing_ok=True)
        return (not path.exists()), ""
    except Exception as exc:  # noqa: BLE001
        return (not path.exists()), str(exc)
