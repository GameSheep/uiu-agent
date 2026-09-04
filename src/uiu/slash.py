"""Slash 命令统一注册表（Hermes COMMAND_REGISTRY 最小版）。

TUI repl 与网关共用同一套：`dispatch(text, ctx)`。
handler 签名：fn(args: str, ctx: SlashContext) -> str|None，返回 "__quit__" 表示退出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class SlashContext:
    ws: Any = None
    cfg: Any = None          # AppConfig
    client: Any = None
    model: str = ""
    messages: list[dict] | None = None  # TUI 对话（网关为 None）
    chat_id: str = ""        # 网关 chat
    say: Callable[[str], None] | None = None  # 输出到用户
    tool_schemas: list = field(default_factory=list)


REGISTRY: dict[str, dict] = {}


def command(name: str, description: str):
    def deco(fn):
        REGISTRY[name] = {"description": description, "fn": fn}
        return fn
    return deco


def dispatch(text: str, ctx: SlashContext) -> tuple[bool, str | None]:
    """Returns (handled, quit-signal-or-None). Output goes through ctx.say."""
    if not text.startswith("/") or text.startswith("//"):
        return False, None
    parts = text[1:].split(None, 1)
    name, args = parts[0], (parts[1] if len(parts) > 1 else "")
    entry = REGISTRY.get(name)
    if entry is None:
        if ctx.say:
            ctx.say(f"未知命令: /{name} — /help 查看全部命令")
        return True, None
    try:
        out = entry["fn"](args, ctx)
    except Exception as e:
        if ctx.say:
            ctx.say(f"[error] /{name}: {type(e).__name__}: {e}")
        return True, None
    if out == "__quit__":
        return True, "__quit__"
    if out and ctx.say:
        ctx.say(out)
    return True, None


def help_text() -> str:
    lines = ["可用命令"]
    for name in sorted(REGISTRY):
        lines.append(f"  /{name:<14} {REGISTRY[name]['description']}")
    return "\n".join(lines)


# ---------- handlers ----------

@command("help", "帮助")
def _help(args: str, ctx: SlashContext):
    return help_text()


@command("skills", "列出 skill（/skills reload 重载）")
def _skills(args: str, ctx: SlashContext):
    from .workspace import load_workspace
    if args.strip() == "reload":
        ctx.ws = load_workspace(ctx.ws.root)
        from . import tools as _tools
        ctx.tool_schemas[:] = _tools.tool_defs() + [s.to_tool_def() for s in ctx.ws.skills]
        return f"(reloaded {len(ctx.ws.skills)} skills)"
    if not ctx.ws.skills:
        return "(no skills loaded — add SKILL.md under workspace/skills/<name>/)"
    return "\n".join(f"- {s.name}  {s.description}" for s in ctx.ws.skills)


@command("tools", "列出内置工具")
def _tools_cmd(args: str, ctx: SlashContext):
    return "\n".join(
        f"- {d['function']['name']}  {d['function'].get('description', '')[:80]}"
        for d in ctx.tool_schemas)


@command("identity", "打印 IDENTITY.md")
def _identity(args: str, ctx: SlashContext):
    return ctx.ws.identity or "(IDENTITY.md is empty)"


@command("model", "切换模型（终端运行 uiu model）")
def _model(args: str, ctx: SlashContext):
    return "模型向导需在终端运行：退出后执行 `uiu model`"


@command("clear", "清空对话上下文")
def _clear(args: str, ctx: SlashContext):
    if ctx.messages is not None:
        from .workspace import Workspace as _W  # noqa
        ctx.messages[:] = [{"role": "system", "content": ctx.ws.system_prompt()}]
        return "(conversation cleared)"
    return "(网关会话由 chat 独立维护，无需 clear)"


@command("quit", "退出")
def _quit(args: str, ctx: SlashContext):
    return "__quit__"


@command("exit", "退出")
def _exit(args: str, ctx: SlashContext):
    return "__quit__"


def _append_md(path, line: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n- {line}\n")


@command("memory", "追加记忆（/memory <内容>）")
def _memory(args: str, ctx: SlashContext):
    note = args.strip()
    if not note:
        return "用法：/memory <内容>"
    try:
        _append_md(ctx.ws.root / "MEMORY.md", note)
    except OSError as e:
        return f"[error] 写入失败: {e}"
    return "(appended to MEMORY.md)"


@command("soul", "追加人设（/soul <内容>）")
def _soul(args: str, ctx: SlashContext):
    line = args.strip()
    if not line:
        return "用法：/soul <内容>"
    try:
        _append_md(ctx.ws.root / "SOUL.md", line)
    except OSError as e:
        return f"[error] 写入失败: {e}"
    return "(appended to SOUL.md — edit file to rearrange)"


@command("save", "保存当前会话（/save [名字]）")
def _save(args: str, ctx: SlashContext):
    from . import sessions as _sessions
    if ctx.messages is None:
        return "(网关会话自动持久化，无需 save)"
    sid = args.strip() or "default"
    _sessions.save_session(ctx.ws.root, sid, ctx.messages)
    return f"(session saved: {sid})"


@command("resume", "恢复会话（/resume [名字]）")
def _resume(args: str, ctx: SlashContext):
    from . import sessions as _sessions
    sid = args.strip() or "default"
    msgs = _sessions.load_session(ctx.ws.root, sid)
    if msgs is None:
        return f"(no saved session: {sid})"
    if ctx.messages is not None:
        ctx.messages[:] = msgs
    return f"(resumed session: {sid}，{len(msgs)} 条)"


@command("sessions", "列出已保存会话（/sessions rm <名字> 删除）")
def _sessions_cmd(args: str, ctx: SlashContext):
    from . import sessions as _sessions
    parts = args.split()
    if len(parts) == 2 and parts[0] == "rm":
        ok = _sessions.remove_session(ctx.ws.root, parts[1])
        return f"(removed {parts[1]})" if ok else f"(no such session: {parts[1]})"
    items = _sessions.list_sessions(ctx.ws.root)
    if not items:
        return "(no saved sessions — /save 先存一个)"
    import time as _t
    return "\n".join(
        f"- {s['id']}  {s['turns']} 轮  {_t.strftime('%m-%d %H:%M', _t.localtime(s['updated']))}"
        for s in items)


@command("cron", "定时任务（add/list/rm/on/off/run/tick）")
def _cron(args: str, ctx: SlashContext):
    from . import cron as _cron
    parts = args.split(None, 1)
    sub = parts[0] if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""
    root = ctx.ws.root
    if sub == "list":
        jobs = _cron.load_jobs(root)
        if not jobs:
            return "(no cron jobs — /cron add <名字> <schedule> <任务>)"
        import time as _t
        lines = []
        for j in jobs:
            nxt = _t.strftime("%m-%d %H:%M", _t.localtime(j["next_run"])) if j.get("next_run") else "-"
            flag = "on" if j.get("enabled") else "off"
            lines.append(f"- {j['name']} [{flag}] {j['schedule']} 下次{nxt}\n  {j['task'][:80]}")
        return "\n".join(lines)
    if sub == "add":
        # /cron add <名字> <schedule...> <任务>  — schedule 取第二段起按规则解析
        segs = rest.split(None, 2)
        if len(segs) < 3:
            return "用法：/cron add <名字> <30m|2h|daily 09:00|'M H * * *'|once ISO> <任务>"
        name, sched, task = segs
        try:
            job = _cron.add_job(root, name, sched, task)
        except ValueError as e:
            return f"[error] {e}"
        return f"(added {job['id']}：{name} @ {sched})"
    if sub in ("rm", "remove"):
        return "(removed)" if _cron.remove_job(root, rest.strip()) else f"(no such job: {rest})"
    if sub in ("on", "enable"):
        return "(enabled)" if _cron.set_enabled(root, rest.strip(), True) else f"(no such job: {rest})"
    if sub in ("off", "disable"):
        return "(disabled)" if _cron.set_enabled(root, rest.strip(), False) else f"(no such job: {rest})"
    if sub == "run":
        jobs = [j for j in _cron.load_jobs(root) if j["id"] == rest.strip() or j["name"] == rest.strip()]
        if not jobs:
            return f"(no such job: {rest})"
        out = _cron.run_job(root, jobs[0])
        return f"(ran → {out})"
    if sub == "tick":
        ran = _cron.tick(root)
        return f"(tick: {len(ran)} 个到期任务已跑)" if ran else "(tick: 无到期任务)"
    return "用法：/cron <list|add|rm|on|off|run|tick>"


def _ctx_stats(ctx: SlashContext) -> tuple[int, int, int]:
    """(user_turns, chars, est_tokens) for status/usage."""
    from . import sessions as _sessions
    msgs = ctx.messages or []
    turns = sum(1 for m in msgs if m.get("role") == "user")
    chars = _sessions.context_chars(msgs)
    return turns, chars, _sessions.estimate_tokens(chars)


@command("status", "状态（模型/会话/上下文/工具）")
def _status(args: str, ctx: SlashContext):
    from . import sessions as _sessions
    from .config import resolve_agent_name as _resolve_name
    turns, chars, toks = _ctx_stats(ctx)
    model = getattr(ctx.cfg, "default", "") or getattr(getattr(ctx.cfg, "model", None), "default", "")
    pct = min(99, int(chars / 1200))  # 120k 上限的百分比（_trim_messages 预算）
    saved = len(_sessions.list_sessions(ctx.ws.root)) if ctx.ws else 0
    return (
        f"agent: {_resolve_name(ctx.cfg, ctx.ws)}\n"
        f"model: {model or '-'}\n"
        f"workspace: {ctx.ws.root if ctx.ws else '-'}\n"
        f"session: {turns} 轮 | ctx约{toks}tok ({pct}%) | 已存会话 {saved} 个\n"
        f"tools: {len(ctx.tool_schemas)} | skills: {len(ctx.ws.skills) if ctx.ws else 0}"
    )


@command("usage", "上下文用量")
def _usage(args: str, ctx: SlashContext):
    turns, chars, toks = _ctx_stats(ctx)
    pct = min(99, int(chars / 1200))
    bar = "#" * (pct // 10) + "-" * (10 - pct // 10)
    return f"[{bar}] {pct}%  约{toks}tok / ~30k  -  {turns} 轮（/clear 清空，/save 存档）"


@command("new", "新会话（当前先自动存档）")
def _new(args: str, ctx: SlashContext):
    if ctx.messages is None:
        return "(网关会话按 chat 独立，无需 new)"
    from . import sessions as _sessions
    import time as _t
    if len(ctx.messages) > 1:
        snap = f"auto-{_t.strftime('%m%d-%H%M%S')}"
        _sessions.save_session(ctx.ws.root, snap, ctx.messages)
        note = f"旧会话已存 {snap}；"
    else:
        note = ""
    ctx.messages[:] = [{"role": "system", "content": ctx.ws.system_prompt()}]
    return f"({note}新会话开始)"
