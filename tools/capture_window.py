"""抓取指定 PID 主窗口位图（PrintWindow，不依赖前台焦点）。"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 0x00000002


def find_window(pid: int) -> int:
    target = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):  # noqa: ANN001
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            target.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return target[0] if target else 0


def capture(pid: int, out: Path) -> bool:
    hwnd = find_window(pid)
    if not hwnd:
        print("未找到窗口")
        return False
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)

    from PySide6.QtGui import QGuiApplication, QImage, QPixmap
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    img = QImage(w, h, QImage.Format_RGB32)
    # 用 GDI 取回像素
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc2 = user32.GetDC(0)
    gdi32.GetDIBits(hdc2, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    user32.ReleaseDC(0, hdc2)
    gdi32.DeleteObject(bmp)
    image = QImage(buf, w, h, QImage.Format_RGB32).copy()
    image.save(str(out))
    print(f"saved {out} {w}x{h}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("out")
    args = ap.parse_args()
    return 0 if capture(args.pid, Path(args.out)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
