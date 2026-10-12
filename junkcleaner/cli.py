"""命令行入口：--guard 后台守护 / --scan 控制台扫描 / --clean 自动清理。"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import APP_NAME, __version__, cleaner, core, guard, scanner


def _cmd_scan(args: argparse.Namespace) -> int:
    def progress(stage: str, ratio: float) -> None:
        print(f"\r[{int(ratio * 100):3d}%] {stage:<28}", end="", flush=True)

    print(f"{APP_NAME} v{__version__} - 扫描")
    findings = scanner.scan(progress=progress, include_disputed=not args.exclude_disputed)
    print()
    if not findings:
        print("未发现命中的垃圾/流氓软件。")
        return 0
    print(f"\n命中 {len(findings)} 个家族：\n")
    print(f"{'等级':<6}{'名称':<40}{'厂商':<20}{'证据':<6}{'占用':<10}")
    print("-" * 90)
    for f in findings:
        print(f"{f.risk:<8}{f.name:<42}{f.vendor:<22}"
              f"{f.evidence_count:<8}{core.human_size(f.computed_size):<10}")
    if args.json:
        import json
        print("\n" + json.dumps([f.to_dict() for f in findings],
                                ensure_ascii=False, indent=2))
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    findings = [f.to_dict() for f in scanner.scan(include_disputed=False)]
    if args.risk != "all":
        allowed = {"rogue": {"rogue"},
                   "bundle": {"rogue", "bundle"}}[args.risk]
        findings = [f for f in findings if f["risk"] in allowed]
    if not findings:
        print("没有需要清理的项目。")
        return 0
    print(f"将清理 {len(findings)} 项：")
    for f in findings:
        print(f"  - [{f['risk']}] {f['name']}")
    if not args.yes:
        answer = input("确认执行？输入 yes 继续：").strip().lower()
        if answer != "yes":
            print("已取消。")
            return 1
    reports = cleaner.clean_many(findings, uninstall=not args.no_uninstall,
                                 purge_files=not args.no_purge)
    for rep in reports:
        print(f"  {rep.name}: 成功 {rep.ok_count} 失败 {rep.fail_count} "
              f"隔离 {core.human_size(rep.freed_bytes)}")
    return 0


def _cmd_guard(args: argparse.Namespace) -> int:
    if not core.is_admin() and not args.allow_non_admin:
        print("拦截守护需要管理员权限。")
        return 2
    watcher = guard.InstallerWatcher(
        notify=lambda t, m: print(f"[通知] {t}: {m}", flush=True),
        interval=float(args.interval))
    watcher.start()
    print(f"{APP_NAME} 守护已启动（间隔 {args.interval}s）。Ctrl+C 退出。")
    try:
        while True:
            time.sleep(2)
            s = watcher.stats
            core.write_status(guard_running=True, guard_stats=dict(s),
                              guard_updated=time.time())
    except KeyboardInterrupt:
        watcher.stop()
        print("\n守护已停止。")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    print(f"{APP_NAME} v{__version__}")
    print(f"数据目录：{core.data_dir()}")
    print(f"管理员：{'是' if core.is_admin() else '否'}")
    print(f"开机自启：{'已启用（静默托盘）' if guard.autostart_installed() else '未启用'}")
    last = scanner.load_last_scan()
    print(f"上次扫描：{len(last)} 项")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="junkcleaner", description=f"{APP_NAME} 命令行")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("scan", help="扫描垃圾/流氓软件")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--exclude-disputed", action="store_true")
    sp.set_defaults(func=_cmd_scan)

    cp = sub.add_parser("clean", help="扫描并清理")
    cp.add_argument("--risk", choices=["rogue", "bundle", "all"], default="bundle")
    cp.add_argument("--yes", action="store_true")
    cp.add_argument("--no-uninstall", action="store_true")
    cp.add_argument("--no-purge", action="store_true")
    cp.set_defaults(func=_cmd_clean)

    gp = sub.add_parser("guard", help="后台拦截守护")
    gp.add_argument("--interval", type=float, default=1.5)
    gp.add_argument("--allow-non-admin", action="store_true")
    gp.set_defaults(func=_cmd_guard)

    st = sub.add_parser("status", help="显示状态")
    st.set_defaults(func=_cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()
    ns = parser.parse_args(argv)
    if not getattr(ns, "func", None):
        parser.print_help()
        return 0
    return int(ns.func(ns) or 0)
