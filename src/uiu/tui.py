"""TUI: Rich for pretty output + prompt_toolkit for multiline input with history."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openai import OpenAI
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import tools
from .agent import run_turn
from .workspace import Workspace, load_workspace

console = Console()

# 符号在 UTF-8 终端显示，管道/GBK 终端自动降级 ASCII（防 UnicodeEncodeError）
def _g(glyph: str, ascii_fb: str) -> str:
    try:
        if sys.stdout.isatty():
            return glyph
    except Exception:
        pass
    return ascii_fb

# ---------- formatting helpers ----------

SLASH_HELP = """\
[bold]Available commands[/bold]
  /help              show this help
  /skills            list loaded skills
  /skills reload     reload skills from disk
  /tools             list built-in tools
  /memory <text>     append a note to MEMORY.md
  /soul <text>       append a line to SOUL.md (edit file to arrange)
  /identity          print IDENTITY.md
  /model             how to switch model (run `uiu model` in shell)
  /clear             clear conversation history
  /quit, /exit       exit
"""


def _print_assistant_header(name: str = "agent") -> None:
    console.print(f"\n[bold cyan]{_g('▌', '|')} {name}[/bold cyan]")


def _stream_markdown(text: str) -> None:
    console.print(Markdown(text))


def _print_tool_call(name: str, args: dict) -> None:
    preview = json.dumps(args, ensure_ascii=False)
    if len(preview) > 200:
        preview = preview[:200] + _g("…", "...")
    console.print(f"  [dim yellow]{_g('⚙', '*')} {name}[/dim yellow] [dim]{preview}[/dim]")


def _print_tool_result(name: str, result: str) -> None:
    one_line = " ".join((result or "").split()
                        ) if not (result or "").startswith("[error]") else (result or "")
    if one_line.startswith("[error]"):
        console.print(f"  [red]{_g('✗', 'X')} {name}[/red] [dim]{one_line[:200]}[/dim]")
    else:
        preview = one_line[:200] + (_g("…", "...") if len(one_line) > 200 else "")
        console.print(f"  [dim]{_g('↳', '>')} {_g('✓', 'ok')} {name}[/dim] [dim]{preview}[/dim]")


# ---------- main REPL ----------

def _rebuild_skill_schemas(ws) -> list:
    """Recompute tool schemas (built-ins + current skills)."""
    schemas = tools.tool_defs()
    for s in ws.skills:
        schemas.append(s.to_tool_def())
    return schemas


class _RunState:
    """Mutable status-line state (read by the bottom toolbar each prompt)."""
    def __init__(self) -> None:
        self.mode = "idle"  # idle | running | error


def _toolbar_html(state: _RunState, model: str, messages, n_tools: int, n_skills: int,
                  agent: str = "agent") -> str:
    from . import sessions as _sessions
    chars = _sessions.context_chars(messages)
    pct = min(99, int(chars / 1200))  # 120k trim 预算的百分比
    toks = _sessions.estimate_tokens(chars)
    turns = sum(1 for m in (messages or []) if m.get("role") == "user")
    dot = {"idle": "ansigreen", "running": "ansiyellow", "error": "ansired"}.get(state.mode, "ansigreen")
    meter = "#" * (pct // 10) + "-" * (10 - pct // 10)
    return (
        f"<{dot}>●</{dot}> {state.mode}  {agent} · {model or '-'}  "
        f"turns:{turns}  ctx:[{meter}] {pct}%  tok≈{toks}  tools:{n_tools} skills:{n_skills}"
    )


def _notice(text: str) -> None:
    console.print(f"[dim]· {text}[/dim]")


UIU_LOGO = """\
 #   #  ###  #   #
 #   #   #   #   #
 #   #   #   #   #
  ###   ###   ###"""


def build_banner(ws, model_name: str, tool_schemas: list, resumed: bool, app_cfg=None) -> str:
    """Hermes-style startup banner: logo + grouped tools/skills + session line."""
    from . import tools as _tools
    try:
        from . import __version__ as _ver
    except Exception:
        _ver = ""
    lines = [UIU_LOGO, ""]
    try:
        from .config import resolve_agent_name as _resolve
        aname = _resolve(app_cfg, ws)
    except Exception:
        aname = ws.agent_name() if hasattr(ws, "agent_name") else "agent"
    lines.append(f"{aname} · {model_name or '-'} · {ws.root}  (uiu v{_ver})")
    lines.append("")
    lines.append("Available Tools")
    for label, names in _tools.tool_groups():
        shown = ", ".join(names[:8]) + (f", +{len(names) - 8} more" if len(names) > 8 else "")
        lines.append(f"  {label}: {shown}")
    if ws.skills:
        lines.append("")
        lines.append("Available Skills")
        lines.append("  " + ", ".join(s.name for s in ws.skills[:20])
                     + (f", +{len(ws.skills) - 20} more" if len(ws.skills) > 20 else ""))
    lines.append("")
    summary = f"{len(tool_schemas)} tools · {len(ws.skills)} skills · /help for commands"
    if resumed:
        summary += " · 上次会话已恢复（/new 开新会话）"
    lines.append(summary)
    return "\n".join(lines)


def repl(client: OpenAI, ws: Workspace, model: str = "", cfg=None, app_cfg=None) -> int:
    history_path = ws.root / "logs" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    state = _RunState()

    def _aname() -> str:
        try:
            from .config import resolve_agent_name as _resolve
            return _resolve(app_cfg if app_cfg is not None else cfg, ws)
        except Exception:
            return "agent"

    def _make_toolbar(st):
        try:
            from prompt_toolkit.formatted_text import HTML
            _model = model if isinstance(model, str) else getattr(cfg, "default", "")
            return lambda: HTML(_toolbar_html(st, _model, messages, len(tool_schemas),
                                              len(ws.skills), _aname()))
        except Exception:
            return None

    # Rich console may also fail on odd consoles; fall back to plain print
    try:
        session: PromptSession = PromptSession(history=FileHistory(str(history_path)))
        rich_ok = True
    except Exception:
        session = None
        rich_ok = False

    system_prompt = ws.system_prompt()
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # 自动恢复上次会话（历史加载；/new 开新会话）
    prev = None
    try:
        from .sessions import load_session as _load_session
        prev = _load_session(ws.root, "default")
        if prev and len(prev) > 1:
            messages = prev
    except Exception:
        prev = None

    # Build tool schemas: built-ins + skills (skills loaded as tools too)
    tool_schemas = _rebuild_skill_schemas(ws)
    if session is not None:
        _tb = _make_toolbar(state)
        if _tb is not None:
            session.bottom_toolbar = _tb  # type: ignore[attr-defined]

    # 宿主上下文注入：子 agent 派发 + clarify 反问共用
    try:
        from .delegation import set_context as _set_delegation_ctx
        _set_delegation_ctx(client, cfg, ws, tool_schemas)
    except Exception:
        pass

    def _tui_ask(question: str, options: list[str] | None) -> str:
        console.print(f"\n[bold yellow]{_g('❓', '?')} {question}[/bold yellow]")
        if options:
            for i, o in enumerate(options, 1):
                console.print(f"   {i}. {o}")
        try:
            if session is not None:
                with patch_stdout():
                    return session.prompt("▌ answer> ").strip()
            return input("answer> ").strip()
        except (KeyboardInterrupt, EOFError):
            return ""

    try:
        from .clarify import set_ask_handler as _set_ask
        _set_ask(_tui_ask)
    except Exception:
        pass

    if rich_ok:
        _model_name = model if isinstance(model, str) else getattr(cfg, "default", "")
        console.print(Panel(
            build_banner(ws, _model_name, tool_schemas,
                         bool(prev and len(prev) > 1), app_cfg),
            border_style="green",
        ))

    turn_count = 0  # for periodic self-learn nudge
    first_prompt = True

    while True:
        # 空行分隔上一轮：用户输入和接下来的 agent 回复视觉上成组
        if not first_prompt:
            console.print()
        first_prompt = False
        try:
            if session is not None:
                try:
                    with patch_stdout():
                        user_input = session.prompt("▌ you> ")
                except Exception:
                    # patch_stdout/session unusable on this console → degrade
                    session = None
                    user_input = input("you> ") if hasattr(sys.stdin, "isatty") and sys.stdin.isatty() else sys.stdin.readline().strip()
            else:
                # Degraded REPL (no proper console) — plain input
                if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                    user_input = input("you> ")
                else:
                    line = sys.stdin.readline()
                    if not line:
                        raise EOFError
                    user_input = line.strip()
        except KeyboardInterrupt:
            console.print("\n[dim](ctrl-c — press ctrl-d or /quit to exit)[/dim]")
            continue
        except EOFError:
            console.print("\n[dim]bye.[/dim]")
            return 0

        text = user_input.strip()
        if not text:
            continue
        if text.startswith("/") and not text.startswith("//"):
            from .slash import SlashContext, dispatch
            say_out: list[str] = []
            sctx = SlashContext(ws=ws, cfg=app_cfg if app_cfg is not None else cfg, client=client, model=model,
                                 messages=messages, say=say_out.append,
                                 tool_schemas=tool_schemas)
            handled, quit_sig = dispatch(text, sctx)
            ws = sctx.ws  # skills reload 可能换了 ws
            if say_out:
                console.print("\n".join(say_out))
            if quit_sig == "__quit__":
                return 0
            if handled:
                continue

        # --- normal user turn ---
        messages.append({"role": "user", "content": text})
        if session is None:
            # 降级终端 prompt_toolkit 不回显输入，这里补一行；正常模式输入行已留在屏幕上，不重复
            console.print(f"[bold green]{_g('›', '>')} you[/bold green] [dim]{text[:2000]}[/dim]")
        _print_assistant_header(_aname())
        state.mode = "running"

        # tty 直播 token；管道/重定向则缓冲后整段渲染（防 GBK 中途炸）
        try:
            _live_stream = bool(sys.stdout.isatty())
        except Exception:
            _live_stream = False
        _stream_buf: list[str] = []

        def _on_text(delta: str) -> None:
            if not delta:
                return
            if _live_stream:
                try:
                    console.print(delta, end="", soft_wrap=True, crop=False)
                    return
                except Exception:
                    pass
            _stream_buf.append(delta)

        def _finish_stream() -> None:
            if _live_stream:
                console.print()  # 结束本行
            elif _stream_buf:
                text = "".join(_stream_buf)
                if text.strip():
                    _stream_markdown(text)
                _stream_buf.clear()

        def _on_tool(name: str, args: dict) -> None:
            _print_tool_call(name, args)

        def _on_tool_result(name: str, result: str) -> None:
            _print_tool_result(name, result)

        def _autosave() -> None:
            try:
                from .sessions import save_session as _save_session
                _save_session(ws.root, "default", messages)
            except Exception:
                pass

        import time as _time
        _turn_start = _time.time()

        try:
            run_turn(
                client=client,
                messages=messages,
                tool_schemas=tool_schemas,
                skills=ws.skills,
                model=model,
                cfg=cfg,
                on_text=_on_text,
                on_tool_call=_on_tool,
                on_tool_result=_on_tool_result,
                on_notice=_notice,
            )
            _finish_stream()
            state.mode = "idle"
            _notice(f"用时 {_time.time() - _turn_start:.1f}s")
            _autosave()
            if session is None:
                # 降级终端没有 bottom toolbar：打一行纯文本状态
                bar = _toolbar_html(state,
                                    model if isinstance(model, str) else getattr(cfg, "default", ""),
                                    messages, len(tool_schemas), len(ws.skills), _aname())
                for tag in ("<ansigreen>", "</ansigreen>", "<ansiyellow>", "</ansiyellow>",
                            "<ansired>", "</ansired>"):
                    bar = bar.replace(tag, "")
                _notice(bar.replace("●", "o").replace("≈", "~"))
            # periodic self-learn nudge (Hermes "nudges itself to persist knowledge")
            turn_count += 1
            if turn_count % 5 == 0:
                try:
                    from .learning import nudge_prompt
                    console.print(f"\n[dim]{_g('⋯', '...')} 自学习检查[/dim]")
                    messages.append({"role": "user", "content": nudge_prompt()})
                    run_turn(
                        client=client,
                        messages=messages,
                        tool_schemas=tool_schemas,
                        skills=ws.skills,
                        model=model,
                        cfg=cfg,
                        on_text=_on_text,
                        on_tool_call=_on_tool,
                        on_tool_result=_on_tool_result,
                    )
                    _finish_stream()
                    # reload skills so newly created ones are picked up
                    ws = load_workspace(ws.root)
                    tool_schemas = _rebuild_skill_schemas(ws)
                    _autosave()
                except Exception as e:
                    console.print(f"[dim](nudge skipped: {e})[/dim]")
        except KeyboardInterrupt:
            state.mode = "idle"
            console.print("\n[dim](interrupted)[/dim]")
        except Exception as e:
            state.mode = "error"
            err_type = type(e).__name__
            msg = str(e)
            hint = ""
            if "401" in msg or "AuthenticationError" in err_type or "invalid_api_key" in msg.lower():
                hint = "  [yellow]→ API key 无效。运行: uiu config --api-key 新key  (或 /model 换 provider)[/yellow]"
            elif "context_length" in msg.lower() or "maximum context" in msg.lower():
                hint = "  [yellow]→ 对话太长。用 /clear 清空后重试[/yellow]"
            elif "timeout" in msg.lower() or "timed out" in msg.lower():
                hint = "  [yellow]→ 请求超时，请重试（网络慢？）[/yellow]"
            console.print(f"[red][error][/red] {err_type}: {msg[:200]}")
            if hint:
                console.print(hint)