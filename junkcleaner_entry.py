#!/usr/bin/env python3
"""JunkCleaner 入口：无参数启动 GUI，--guard 启动后台守护。

注意：打包后必须先修正 DLL 搜索路径再导入 PySide6。否则系统 PATH 上若有
其它软件自带的旧版 Qt6Core.dll（例如 STM32CubeProgrammer 的 Qt 6.6.1），
会被优先加载，导致 PySide6 报「找不到指定的程序」而无法启动。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_frozen_dll_path() -> None:
    """冻结环境下修正 DLL 搜索顺序。

    打包机/运行机的 PATH 上可能存在与 Qt6 不兼容的同名 DLL，典型来源：
      * 旧版 Qt6Core.dll（如 STM32CubeProgrammer 自带的 Qt 6.6.1）
      * 更新的 ucrtbase.dll（如 10.0.26100，而本机系统是 10.0.19041）
    这些会先于自带库被加载，导致：
      ImportError: DLL load failed while importing QtCore: 找不到指定的程序

    处理办法：从 PATH 中剔除带这些同名 DLL 的目录，并把自带库目录前置。
    """
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return

    conflict_names = ("qt6core.dll", "qt6gui.dll", "qt6widgets.dll",
                      "ucrtbase.dll", "msvcp140.dll", "vcruntime140.dll")
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32").lower()
    kept: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        low = entry.lower()
        # 系统目录必须保留（提供正确的系统 DLL）
        if low.startswith(system32):
            kept.append(entry)
            continue
        try:
            names = {n.lower() for n in os.listdir(entry)}
        except OSError:
            kept.append(entry)
            continue
        if names & set(conflict_names):
            # 该目录含有冲突 DLL，移出搜索路径
            continue
        kept.append(entry)
    os.environ["PATH"] = os.pathsep.join([base, *kept])

    # 显式加入自带库目录（优先级高于 PATH）
    for sub in ("", "PySide6", "shiboken6"):
        d = os.path.join(base, sub) if sub else base
        if os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except Exception:  # noqa: BLE001
                pass

    # 预加载正确的 Qt6Core，锁定版本
    try:
        import ctypes
        for candidate in (os.path.join(base, "PySide6", "Qt6Core.dll"),
                          os.path.join(base, "Qt6Core.dll")):
            if os.path.exists(candidate):
                ctypes.CDLL(candidate)
                break
    except Exception:  # noqa: BLE001
        pass


_prepare_frozen_dll_path()
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def _boot_log(msg: str) -> None:
    """启动阶段写日志（仅 JUNKCLEANER_DEBUG=1 时启用）。"""
    if not os.environ.get("JUNKCLEANER_DEBUG"):
        return
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
            else str(Path(__file__).resolve().parent)
        path = os.path.join(base, "startup.log")
        import datetime as _dt
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_dt.datetime.now():%Y-%m-%d %H:%M:%S}\t{msg}\n")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    argv = sys.argv[1:]
    _boot_log(f"main() argv={argv} frozen={getattr(sys, 'frozen', False)}")
    # 开机自启：--tray 表示启动后直接隐藏到右下角托盘运行。
    # 必须放在 --guard 之前判断，否则会被当成无界面的命令行守护。
    if "--tray" in argv:
        os.environ["JUNKCLEANER_START_TRAY"] = "1"
        argv = [a for a in argv if a != "--tray"]
    if "--guard" in argv:
        from junkcleaner import cli
        argv = [a for a in argv if a != "--guard"]
        return cli.main(["guard", *argv])
    if "--gpu-apply" in argv:
        # 开机固化：重新应用保存的 GPU 频率/功耗设置
        from junkcleaner import gpu
        _boot_log("applying saved GPU profile ...")
        return 0 if gpu.apply_saved_profile().get("ok") else 1
    if "--gpu-stress-check" in argv:
        # 诊断用：只跑压测，不读写任何显卡电压/频率设置。
        from junkcleaner import gpu_load
        import time as _time
        print("backend:", gpu_load.stress_backend())
        print("exe    :", gpu_load.stress_exe_path())
        s = gpu_load.GpuStress(transient=True)
        s.start()
        _time.sleep(6)
        print("running:", s.running, "backend:", s.backend)
        print("errors :", s.errors)
        print("summary:", s.summary())
        s.stop()
        return 0 if (s.backend != "none" and not s.errors) else 1
    if "--cpu-bench-worker" in argv:
        # CPU 多核跑分的子进程：只跑负载并输出耗时，不启动 GUI
        from junkcleaner import cpubench
        idx = argv.index("--cpu-bench-worker")
        return cpubench.worker_cli(argv[idx + 1:])
    if argv and argv[0] != "--gui":
        from junkcleaner import cli
        return cli.main(argv)
    _boot_log("importing junkcleaner.gui ...")
    from junkcleaner import gui
    _boot_log("gui imported, starting run_gui ...")
    return gui.run_gui([sys.argv[0], *[a for a in argv if a != "--gui"]])


if __name__ == "__main__":
    os.environ.setdefault("JUNKCLEANER_VERBOSE", "0")
    # 冻结环境下必须调用：CPU 跑分使用 multiprocessing，
    # 子进程会重新执行本入口；没有它子进程会再次启动整个 GUI
    # （或直接因句柄/权限失败），表现为「跑分没反应」。
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
