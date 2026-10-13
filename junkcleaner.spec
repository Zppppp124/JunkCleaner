# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、无控制台、带管理员清单。

构建：python -m PyInstaller junkcleaner.spec --noconfirm
输出：dist\\JunkCleaner.exe
"""

import os
import sys

block_cipher = None

# 资源：图标始终带上；Afterburner 内嵌安装包按需带上。
#   内嵌：设 JUNKCLEANER_BUNDLE_AB=1 后打包（体积约 +42MB）
#   不内嵌：默认（体积约 54MB），程序会在运行时提示联网或手动放置
_datas = [
    ("junkcleaner/assets/app.ico", "junkcleaner/assets"),
    ("junkcleaner/assets/app.png", "junkcleaner/assets"),
]
# 显存测试工具（zlib 许可，允许随程序分发，需保留版权声明）
_vram_exe = "junkcleaner/assets/memtest_vulkan.exe"
_vram_lic = "junkcleaner/assets/LICENSE-memtest_vulkan.txt"
for _f in (_vram_exe, _vram_lic):
    if os.path.exists(_f):
        _datas.append((_f, "junkcleaner/assets"))
        print(f"[spec] 内嵌 {_f}")
    else:
        print(f"[spec] 警告：缺少 {_f}")

# NVAPI 降压工具（MIT 许可，允许随程序分发，需保留版权声明）
# 有了它就不再需要 MSI Afterburner（专有软件，不可再分发）。
_nv_exe = "junkcleaner/assets/simple-nvidia-undervolt.exe"
_nv_lic = "junkcleaner/assets/LICENSE-simple-nvidia-undervolt.txt"
for _f in (_nv_exe, _nv_lic):
    if os.path.exists(_f):
        _datas.append((_f, "junkcleaner/assets"))
        print(f"[spec] 内嵌 {_f}")
    else:
        print(f"[spec] 警告：缺少 {_f}")
if os.environ.get("JUNKCLEANER_BUNDLE_AB") == "1":
    _ab_zip = "junkcleaner/assets/MSIAfterburnerSetup.zip"
    if os.path.exists(_ab_zip):
        _datas.append((_ab_zip, "junkcleaner/assets"))
        print(f"[spec] 内嵌 Afterburner 安装包: {_ab_zip}")
    else:
        print(f"[spec] 警告：指定内嵌但文件不存在 {_ab_zip}")

# 只保留需要的 Qt 模块，显著减小体积
hiddenimports = [
    "psutil", "win32api", "win32con", "win32file", "win32event",
    "win32service", "win32serviceutil", "pywintypes", "pythoncom",
    "win32com.client", "wmi", "PIL",
    "junkcleaner.archive", "junkcleaner.defender", "junkcleaner.memory",
    "junkcleaner.ui_defender", "junkcleaner.ui_memory", "junkcleaner.ui_trust",
    "junkcleaner.power", "junkcleaner.gpu", "junkcleaner.ui_tuning",
    "junkcleaner.vfcurve", "junkcleaner.undervolt", "junkcleaner.gpu_load",
    "junkcleaner.fan", "junkcleaner.hwinfo", "junkcleaner.cpubench",
    "junkcleaner.gpu_live",
    "junkcleaner.localgpo",
    "junkcleaner.nvbackend", "junkcleaner.nvundervolt",
    "junkcleaner.memtest", "junkcleaner.ui_hardware",
    "junkcleaner.afterburner", "junkcleaner.silent_uninstall",
    "junkcleaner.vramtest",
]

# 不手工收集 Qt 全部库（会让体积涨到 190MB+，且曾破坏归档完整性）。
# 由 PyInstaller 的 PySide6 hook 自动收集必需部分，
# DLL 搜索顺序问题改为运行时修正（见 junkcleaner_entry.py）。
binaries = []

excludes = [
    "PyQt5", "PyQt6", "tkinter", "matplotlib", "numpy", "scipy", "pandas",
    "IPython", "jupyter", "pytest", "setuptools", "pip", "wheel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtWebSockets",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtSvgWidgets",
]

a = Analysis(
    ["junkcleaner_entry.py"],
    pathex=[],
    binaries=binaries,
    # 带上应用图标资源（窗口/托盘运行时加载）
    datas=_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="JunkCleaner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 请求管理员权限（UAC）——PyInstaller 原生支持，
    # 用 manifest= 会被它自带的 asInvoker 清单覆盖，故用 uac_admin。
    uac_admin=True,
    # EXE 文件图标（资源管理器里看到的图标）
    icon="junkcleaner/assets/app.ico",
    # 文件属性中的版本信息
    version="version_info.txt",
)
