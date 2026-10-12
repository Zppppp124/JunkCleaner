"""打印上次扫描的证据链，用于人工核验误报。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from junkcleaner import core, scanner  # noqa: E402


def main() -> None:
    rows = scanner.load_last_scan()
    print(f"数据目录: {core.data_dir()}")
    for f in rows:
        print("=" * 70)
        print(f"{f['name']}  [{f['risk']}]  {f['vendor']}  证据={f.get('sig_id')}")
        for key in ("uninstall_entries", "processes", "services", "tasks", "startup", "paths"):
            items = f.get(key) or []
            if not items:
                continue
            print(f"  {key} ({len(items)}):")
            for it in items:
                if isinstance(it, dict):
                    keep = {k: v for k, v in it.items()
                            if k in ("display_name", "publisher", "version", "install_location",
                                     "subkey", "hive", "name", "pid", "exe", "display",
                                     "state", "path")}
                    print("     ", keep)
                else:
                    print("     ", it)


if __name__ == "__main__":
    main()
