"""探测实时事件源可用性：WMI 进程启动追踪 + ReadDirectoryChangesW。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def probe_wmi(seconds: float = 4.0) -> bool:
    try:
        import pythoncom
        import wmi
    except ImportError as exc:
        print(f"WMI 不可用: {exc}")
        return False
    got: list[str] = []

    def worker() -> None:
        pythoncom.CoInitialize()
        try:
            c = wmi.WMI()
            watcher = c.Win32_ProcessStartTrace.watch_for()
            end = time.time() + seconds
            while time.time() < end:
                try:
                    evt = watcher(timeout_ms=500)
                except Exception:  # noqa: BLE001
                    continue
                if evt is not None:
                    got.append(str(getattr(evt, "ProcessName", "?")))
                    if len(got) >= 3:
                        return
        finally:
            pythoncom.CoUninitialize()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    time.sleep(0.8)
    for _ in range(2):
        subprocess.Popen(["cmd", "/c", "echo probe"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x08000000)
        time.sleep(0.4)
    t.join(timeout=seconds + 2)
    print(f"WMI 捕获进程启动事件: {got}")
    return len(got) > 0


def probe_rdc(seconds: float = 4.0) -> bool:
    try:
        import pywintypes
        import win32con
        import win32event
        import win32file
    except ImportError as exc:
        print(f"pywin32 不可用: {exc}")
        return False
    tmp = Path(tempfile.mkdtemp(prefix="jc_rt_"))
    handle = win32file.CreateFile(
        str(tmp), win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_BACKUP_SEMANTICS | win32con.FILE_FLAG_OVERLAPPED, None)
    buf = win32file.AllocateReadBuffer(65536)
    ov = pywintypes.OVERLAPPED()
    ov.hEvent = win32event.CreateEvent(None, True, False, None)
    hits: list[str] = []

    def arm() -> None:
        win32event.ResetEvent(ov.hEvent)
        win32file.ReadDirectoryChangesW(
            handle, buf, True,
            win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE,
            ov, None)

    arm()

    def trigger() -> None:
        time.sleep(1.0)
        (tmp / "payload.exe").write_bytes(b"MZ")

    threading.Thread(target=trigger, daemon=True).start()
    rc = win32event.WaitForSingleObject(ov.hEvent, int(seconds * 1000))
    print(f"事件等待结果: {rc} (0=WAIT_OBJECT_0)")
    if rc == 0:
        try:
            n = win32file.GetOverlappedResult(handle, ov, False)
            print(f"传输字节: {n}")
            hits.append(f"bytes={n}")
        except Exception as exc:  # noqa: BLE001
            print(f"GetOverlappedResult 异常: {exc}")
    try:
        win32file.CancelIo(handle)
    except Exception:  # noqa: BLE001
        pass
    win32file.CloseHandle(handle)
    print(f"目录变更捕获: {hits}")
    return len(hits) > 0


if __name__ == "__main__":
    print("== WMI 进程启动追踪 ==")
    a = probe_wmi()
    print("\n== 目录变更通知 ==")
    b = probe_rdc()
    print(f"\nWMI={'OK' if a else 'FAIL'}  DIR={'OK' if b else 'FAIL'}")
