"""一键打包成单文件 EXE（需管理员权限清单）。

为什么固定版本：
    PySide6 6.11.x 与 PyInstaller 6.x 组合在本机会出现
    "DLL load failed while importing QtCore"，实测 6.8.3 + 6.11.1 稳定。
    因此优先使用 .buildvenv（若存在），否则用当前解释器并提示。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".buildvenv" / "Scripts" / "python.exe"

REQUIRED = [
    "PySide6==6.8.3",
    "pyinstaller==6.11.1",
    "psutil", "pywin32", "wmi", "py7zr", "pillow",
]


def ensure_venv(recreate: bool = False) -> Path:
    """确保存在固定版本的构建环境，返回其 python.exe。"""
    if VENV_PY.exists() and not recreate:
        return VENV_PY
    base = sys.executable
    print("创建构建环境 .buildvenv …")
    subprocess.run([base, "-m", "venv", str(ROOT / ".buildvenv")], check=True)
    index = ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
             "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]
    print("安装固定版本依赖 …")
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", *REQUIRED, *index],
                   check=True)
    return VENV_PY


def main() -> int:
    print("=" * 60)
    print(" JunkCleaner 打包")
    print("=" * 60)

    # --bundle-ab：把 Afterburner 安装包一起打进 exe（体积 +42MB）
    bundle_ab = "--bundle-ab" in sys.argv
    if bundle_ab:
        os.environ["JUNKCLEANER_BUNDLE_AB"] = "1"
        print("模式：内嵌 Afterburner 安装包（开箱即用，体积更大）")
    else:
        os.environ.pop("JUNKCLEANER_BUNDLE_AB", None)
        print("模式：标准（需要 Afterburner 时再联网获取或手动放置）")
    print("-" * 60)
    try:
        py = ensure_venv()
    except Exception as exc:  # noqa: BLE001
        print(f"构建环境准备失败：{exc}\n改用当前解释器（可能不兼容）")
        py = Path(sys.executable)
    print(f"使用解释器: {py}")
    cmd = [str(py), "-m", "PyInstaller", "junkcleaner.spec",
           "--noconfirm", "--clean"]
    proc = subprocess.run(cmd, cwd=ROOT)
    if proc.returncode != 0:
        print(f"\n打包失败，退出码 {proc.returncode}")
        return proc.returncode
    exe = ROOT / "dist" / "JunkCleaner.exe"
    if not exe.exists():
        print("\n未找到输出文件")
        return 1
    size = exe.stat().st_size / (1 << 20)
    print("\n" + "=" * 60)
    print(f" 打包完成: {exe}")
    print(f" 体积: {size:.1f} MB")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
