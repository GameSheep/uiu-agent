"""会话与宏：sessions / macro / quick（自原 commands.py 按域拆分；审计 §2.1）。"""

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
    _confirm_or_abort,
    _print_err,
    _print_ok,
    _session_age_days,
    _session_cap,
    _workspace,
)


def cmd_sessions(args) -> int:
    from . import sessions as _sessions
    ws = _workspace(args)
    action = args.action

    if action == "list":
        from . import cli_io

        items = _sessions.list_sessions(ws)
        usage = _sessions.sessions_usage(ws)
        over = _session_cap(ws)
        data = {"count": usage["count"], "bytes": usage["bytes"], "cap": over,
                "sessions": [{k: s.get(k) for k in ("id", "turns", "bytes", "updated")}
                             for s in items]}
        if not items:
            cli_io.result("sessions.list", data=data,
                          human="(no saved sessions — TUI 里 /save 存一个)")
            return 0
        import time as _t
        lines = []
        for s in items:
            ts = _t.strftime("%m-%d %H:%M", _t.localtime(s["updated"]))
            kb = s.get("bytes", 0) / 1024
            lines.append(f"  {s['id']:<24} {s['turns']:>3} 轮  {kb:>7.1f} KB  {ts}")
        note = f"（上限 {over}，建议 uiu sessions prune）" if over and usage["count"] > over else ""
        lines.append(f"\n  共 {usage['count']} 个 · {usage['bytes'] / 1024 / 1024:.1f} MB {note}")
        cli_io.result("sessions.list", data=data, human="\n".join(lines))
        return 0

    if action == "usage":
        from . import cli_io

        usage = _sessions.sessions_usage(ws)
        over = _session_cap(ws)
        data = {"count": usage["count"], "bytes": usage["bytes"], "cap": over,
                "newest": usage["newest"], "oldest": usage["oldest"],
                "largest": [{"id": r["id"], "bytes": r.get("bytes", 0)}
                            for r in usage["largest"]]}
        if not usage["count"]:
            cli_io.result("sessions.usage", data=data, human="(还没有已保存的会话)")
            return 0
        lines = [f"  会话数: {usage['count']}",
                 f"  占用:   {usage['bytes'] / 1024 / 1024:.2f} MB",
                 f"  最新:   {usage['newest']}",
                 f"  最旧:   {usage['oldest']}",
                 "  最大的几个："]
        lines += [f"    {row['id']:<24} {row.get('bytes', 0) / 1024:>8.1f} KB"
                  for row in usage["largest"]]
        if over and usage["count"] > over:
            lines.append(f"\n  已超过上限 {over}：uiu sessions prune --keep {over}"
                         "（会进回收站，可恢复）")
        cli_io.result("sessions.usage", data=data, human="\n".join(lines))
        return 0

    if action == "prune":
        from . import cli_io

        keep = getattr(args, "keep", None)
        days = getattr(args, "days", None)
        usage = _sessions.sessions_usage(ws)
        # 默认值来自配置，命令行优先
        if keep is None:
            keep = _session_cap(ws)
        if days is None:
            days = _session_age_days(ws)
        plan = _sessions.prune_sessions(ws, keep=int(keep or 0),
                                        max_age_days=float(days or 0),
                                        protect=("default",),
                                        dry_run=True)
        if not plan["removed"]:
            cli_io.result("sessions.prune", data={**plan, "applied": False},
                          human=f"(无需裁剪：共 {usage['count']} 个会话，keep={keep}, days={days})")
            return 0
        head = (f"将裁剪 {len(plan['removed'])} 个会话"
                f"（释放约 {plan['freed'] / 1024:.1f} KB）：")
        listing = "\n".join(f"  - {sid}" for sid in plan["removed"][:20])
        if len(plan["removed"]) > 20:
            listing += f"\n  … 其余 {len(plan['removed']) - 20} 个"

        # JSON 模式不交互：没有 --yes 就只出计划（脚本自己决定要不要真删）
        if getattr(args, "dry_run", False) or (cli_io.json_mode()
                                               and not getattr(args, "yes", False)):
            cli_io.result("sessions.prune", data={**plan, "applied": False},
                          human=f"{head}\n{listing}\n\n(dry-run：没有真的删除)")
            return 0
        if not cli_io.json_mode():
            answer = _confirm_or_abort("确认裁剪？", bool(getattr(args, "yes", False)),
                                       action=f"裁剪 {len(plan['removed'])} 个会话")
            if answer is None:
                cli_io.result("sessions.prune", ok=False, data={**plan, "applied": False},
                              error="非交互环境缺少 --yes", human="")
                return 2
            if not answer:
                cli_io.result("sessions.prune", ok=False, data={**plan, "applied": False},
                              error="用户取消", human="已取消")
                return 0
        result = _sessions.prune_sessions(ws, keep=int(keep or 0),
                                          max_age_days=float(days or 0),
                                          protect=("default",))
        cli_io.result("sessions.prune", data={**result, "applied": True},
                      human=f"{head}\n{listing}\n\n"
                            f"[ok] 已裁剪 {len(result['removed'])} 个会话"
                            "（进回收站，uiu trash 可恢复）")
        return 0

    if action == "show":
        msgs = _sessions.load_session(ws, args.name)
        if msgs is None:
            _print_err(f"没有这个会话: {args.name}")
            return 2
        for m in msgs[-20:]:
            role = m.get("role", "?")
            content = m.get("content", "")
            content = content if isinstance(content, str) else "(non-text)"
            print(f"[{role}] {content[:300]}")
        return 0

    if action == "search":
        hits = _sessions.search_sessions(ws, args.query, limit=args.limit)
        if not hits:
            print("(no matches in saved sessions)")
            return 0
        for h in hits:
            print(f"[{h['session']} · {h['role']}] {h['text'][:600]}")
            for c in h.get("context", []):
                print(f"    · ({c['role']}) {c['text'][:200]}")
        return 0

    if action == "remove":
        if _sessions.remove_session(ws, args.name):
            _print_ok(f"已删除 {args.name}")
            return 0
        _print_err(f"没有这个会话: {args.name}")
        return 2

    return 2


def cmd_macro(args) -> int:
    from . import macros as _macros
    ws = _workspace(args)
    action = args.action

    if action == "list":
        print(_macros.macro_list())
        return 0

    if action == "record":
        if not getattr(args, "yes", False):
            print("录制将真实捕获你的鼠标键盘操作。准备就绪后开始：")
            print("  · 切到目标窗口")
            print("  · 按 F9 结束录制")
            try:
                ans = input("开始录制？[Y/n] ").strip().lower()
            except EOFError:
                ans = "y"
            if ans not in ("", "y", "yes"):
                print("(取消)")
                return 0
        from .macro_recorder import MacroRecorder, macros_dir, save_macro
        import re as _re
        safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", args.name.strip()).strip("_")[:64]
        if not safe:
            _print_err("宏名非法")
            return 2
        path = macros_dir(ws) / f"{safe}.json"
        print(f"· 录制中…（按 F9 停止，--timeout 可设自动停止）")
        rec = MacroRecorder(timeout=max(0, min(args.timeout or 0, 1800)))
        try:
            steps, aborted = rec.run()
        except Exception as e:
            _print_err(f"录制失败: {type(e).__name__}: {e}")
            return 1
        if not steps:
            print("(未捕获到操作，未保存)")
            return 0
        save_macro(path, safe, getattr(args, "desc", "") or "", steps)
        _print_ok(f"已录制宏 '{safe}'：{len(steps)} 步（{'F9 停止' if aborted else '超时自动停'}）→ {path.name}")
        print("  回放: uiu macro play", safe)
        return 0

    if action == "play":
        from .macro_recorder import load_macro
        import re as _re
        safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", args.name.strip()).strip("_")[:64]
        path = ws / "macros" / f"{safe}.json"
        if not path.exists():
            _print_err(f"宏不存在: {safe}")
            return 2
        try:
            macro = load_macro(path)
        except Exception as e:
            _print_err(f"宏文件损坏: {e}")
            return 2
        steps = macro.get("steps", [])
        print(f"宏 '{safe}': {len(steps)} 步 — {macro.get('description', '')}")
        if not getattr(args, "yes", False):
            print("回放将真实控制鼠标键盘。请确保目标窗口已就绪。")
            print("  · 甩鼠标到屏幕左上角 或 按 F9 可紧急中止")
            try:
                ans = input(f"回放 {len(steps)} 步？[Y/n] ").strip().lower()
            except EOFError:
                ans = "y"
            if ans not in ("", "y", "yes"):
                print("(取消)")
                return 0
        from .macro_player import play_steps
        played, status = play_steps(
            steps, speed=max(0.1, float(args.speed or 1.0)),
            start=args.start, end=args.end or None)
        print(f"{status}（{played}/{len(steps)} 步）")
        return 0

    if action == "quick":
        from .quick_macro import QuickMacroDaemon
        import time as _t
        print("╭────────────────────────────────────────────────────────╮")
        print("│  ⚡ uiu 极速按键精灵 (Quick Macro)                     │")
        print("│                                                        │")
        print("│  [F10]      开始录制 / 结束录制（保存为循环宏）         │")
        print("│  [F12]      单次回放刚才录制的动作                     │")
        print("│  [Ctrl+F12] 连续循环 10 次                             │")
        print("│  [F11]      紧急刹车 / 强制中止                        │")
        print("│                                                        │")
        print("│  提示：操作全程伴随系统蜂鸣音提示，无需切回本终端。     │")
        print("│  按 Ctrl+C 退出精灵守护模式。                          │")
        print("╰────────────────────────────────────────────────────────╯")
        daemon = QuickMacroDaemon(ws, on_status_change=lambda st, msg: print(f"  [{st}] {msg}"))
        daemon.start()
        try:
            while True:
                _t.sleep(0.5)
        except KeyboardInterrupt:
            print("\n· 正在退出按键精灵守护...")
        finally:
            daemon.stop()
            print("[ok] 已退出")
        return 0

    if action == "remove":
        from . import macros as _macros_mod
        out = _macros_mod.macro_remove(args.name)
        print(out)
        return 0 if out.startswith("[ok]") else 2

    return 2


def cmd_quick(args) -> int:
    """Shortcut entry for uiu quick."""
    setattr(args, "action", "quick")
    return cmd_macro(args)
