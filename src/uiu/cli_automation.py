"""自动化：cron / daemon（自原 commands.py 按域拆分；审计 §2.1）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import tools
from .config import (
    AppConfig,
    ChannelConfig,
    ModelConfig,
    config_yaml_path,
    ensure_workspace,
    load_config,
    parse_env_file,
    save_config,
    write_env_file,
)
from .workspace import load_workspace


# ---------- helpers ----------

from .cli_shared import (
    _print_err,
    _print_ok,
    _workspace,
)


def cmd_cron(args) -> int:
    from . import cron as _cron
    ws = _workspace(args)
    action = args.action

    if action == "list":
        jobs = _cron.load_jobs(ws)
        if not jobs:
            print("(no cron jobs)")
            print("  add: uiu cron add <name> <30m|2h|daily 09:00> \"<task>\"")
            return 0
        import time as _t
        for j in jobs:
            nxt = _t.strftime("%m-%d %H:%M", _t.localtime(j["next_run"])) if j.get("next_run") else "-"
            flag = "on" if j.get("enabled") else "off"
            kind = "[shell]" if j.get("run_shell") else ""
            print(f"  {j['name']:<20} [{flag}] {j['schedule']:<16} 下次{nxt}  {kind} id={j['id']}")
            print(f"    {j['task'][:100]}")
        return 0

    if action == "add":
        try:
            job = _cron.add_job(ws, args.name, args.schedule, args.task, run_shell=getattr(args, "shell", False))
        except ValueError as e:
            _print_err(str(e))
            return 2
        kind = "shell 命令" if job.get("run_shell") else "agent 任务"
        _print_ok(f"已添加 {job['id']}（{args.name} @ {args.schedule}）")
        print("  serve 运行时每 60s 自动 tick；手动跑: uiu cron run", args.name)
        return 0

    if action == "remove":
        job = next((j for j in _cron.load_jobs(ws)
                    if j["id"] == args.name or j["name"] == args.name), None)
        if _cron.remove_job(ws, args.name):
            if job is not None:
                try:
                    from .trash import add_record
                    add_record(ws, "cron_job", job, label=job.get("name", ""))
                except Exception:
                    pass
            _print_ok(f"removed {args.name}（已移入回收站，uiu trash 可恢复）")
            return 0
        _print_err(f"没有这个定时任务: {args.name}")
        return 2

    if action in ("enable", "disable"):
        if _cron.set_enabled(ws, args.name, action == "enable"):
            verb = "启用" if action == "enable" else "停用"
            _print_ok(f"{args.name} 已{verb}")
            return 0
        _print_err(f"没有这个定时任务: {args.name}")
        return 2

    if action == "run":
        jobs = [j for j in _cron.load_jobs(ws) if j["id"] == args.name or j["name"] == args.name]
        if not jobs:
            _print_err(f"没有这个定时任务: {args.name}")
            return 2
        out = _cron.run_job(ws, jobs[0])
        _print_ok(f"已执行 → {out}")
        return 0

    if action == "tick":
        ran = _cron.tick(ws)
        _print_ok(f"tick: 执行了 {len(ran)} 个任务")
        for out in ran:
            print(f"  {out}")
        return 0

    return 2


def cmd_daemon(args) -> int:
    from . import daemon as _daemon
    ws = _workspace(args)
    action = args.action

    if action == "start":
        ok, msg = _daemon.start_daemon(ws)
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "stop":
        ok, msg = _daemon.stop_daemon()
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "status":
        info = _daemon.status_daemon(ws)
        if info["running"]:
            _print_ok(f"守护进程运行中 (PID: {info['pid']})")
        else:
            print("守护进程未运行 (未启动)")
        print(f"  工作目录: {info['workspace']}")
        print(f"  日志文件: {info['log_path']}")
        print(f"  定时任务: 共 {info['total_jobs']} 个，已启用 {info['enabled_jobs']} 个")
        if info["jobs"]:
            import time as _t
            for j in info["jobs"]:
                nxt = _t.strftime("%m-%d %H:%M", _t.localtime(j["next_run"])) if j.get("next_run") else "-"
                flag = "on" if j.get("enabled") else "off"
                kind = "[shell]" if j.get("run_shell") else "[agent]"
                print(f"    - {j['name']:<18} [{flag}] {j['schedule']:<12} 下次: {nxt} {kind}")
        return 0

    if action == "run":
        interval = getattr(args, "interval", 60)
        print(f"[daemon] 正在前台运行定时任务循环（每 {interval} 秒检查一次）... 按 Ctrl+C 退出")
        _daemon.run_daemon(ws, interval=interval)
        return 0

    if action == "install-autostart":
        ok, msg = _daemon.install_autostart(ws)
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "uninstall-autostart":
        ok, msg = _daemon.uninstall_autostart()
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    return 2
