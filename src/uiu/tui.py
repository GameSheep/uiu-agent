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
from .workspace import Workspace

console = Console()

# ---------- formatting helpers ----------

SLASH_HELP = """\
[bold]Available commands[/bold]
  /help              show this help
  /skills            list loaded skills
  /tools             list built-in tools
  /memory <text>     append a note to MEMORY.md
  /soul <text>       replace a section in SOUL.md (use carefully)
  /identity          print IDENTITY.md
  /clear             clear conversation history
  /quit, /exit       exit
"""


def _print_assistant_header() -> None:
    console.print("\n[bold cyan]▌ agent[/bold cyan]")


def _stream_markdown(text: str) -> None:
    console.print(Markdown(text))


def _print_tool_call(name: str, args: dict) -> None:
    preview = json.dumps(args, ensure_ascii=False)
    if len(preview) > 200:
        preview = preview[:200] + "…"
    console.print(f"  [dim yellow]⚙ {name}[/dim yellow] [dim]{preview}[/dim]")


def _print_tool_result(name: str, result: str) -> None:
    preview = result if len(result) < 800 else result[:800] + "\n…(truncated)"
    console.print(Panel(preview, title=f"[dim]↳ {name}[/dim]", border_style="dim"))


# ---------- main REPL ----------

def repl(client: OpenAI, ws: Workspace, model: str = "", cfg=None) -> int:
    history_path = ws.root / "logs" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    session: PromptSession = PromptSession(history=FileHistory(str(history_path)))

    system_prompt = ws.system_prompt()
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Build tool schemas: built-ins + skills (skills loaded as tools too)
    tool_schemas = tools.tool_defs()
    for skill in ws.skills:
        tool_schemas.append(skill.to_tool_def())

    console.print(Panel.fit(
        f"[bold green]uiu[/bold green] — workspace: {ws.root}\n"
        f"[dim]model: {client.base_url if hasattr(client, 'base_url') else ''} | "
        f"skills: {len(ws.skills)} | built-in tools: 3 | "
        f"type /help for commands[/dim]",
        border_style="green",
    ))

    while True:
        try:
            with patch_stdout():
                user_input = session.prompt("▌ you> ")
        except KeyboardInterrupt:
            console.print("\n[dim](ctrl-c — press ctrl-d or /quit to exit)[/dim]")
            continue
        except EOFError:
            console.print("\n[dim]bye.[/dim]")
            return 0

        text = user_input.strip()
        if not text:
            continue
        if text in ("/quit", "/exit"):
            return 0
        if text == "/help":
            console.print(SLASH_HELP)
            continue
        if text == "/skills":
            if not ws.skills:
                console.print("[dim](no skills loaded — add SKILL.md under workspace/skills/<name>/)[/dim]")
            for s in ws.skills:
                console.print(f"  [cyan]•[/cyan] [bold]{s.name}[/bold]  {s.description}")
            continue
        if text == "/tools":
            for d in tool_schemas:
                console.print(f"  [cyan]•[/cyan] [bold]{d['function']['name']}[/bold]  {d['function']['description'][:80]}")
            continue
        if text == "/identity":
            console.print(Markdown(ws.identity or "(IDENTITY.md is empty)"))
            continue
        if text == "/clear":
            messages = [{"role": "system", "content": system_prompt}]
            console.print("[dim](conversation cleared)[/dim]")
            continue
        if text.startswith("/memory "):
            note = text[len("/memory "):].strip()
            mem = ws.root / "MEMORY.md"
            with mem.open("a", encoding="utf-8") as f:
                f.write(f"\n- {note}\n")
            console.print(f"[dim](appended to MEMORY.md)[/dim]")
            continue

        # --- normal user turn ---
        messages.append({"role": "user", "content": text})
        _print_assistant_header()

        def _on_text(delta: str) -> None:
            # In tool-loop mode text comes in one chunk at the end; render as markdown.
            if delta.strip():
                _stream_markdown(delta)

        def _on_tool(name: str, args: dict) -> None:
            _print_tool_call(name, args)

        def _on_tool_result(name: str, result: str) -> None:
            _print_tool_result(name, result)

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
            )
        except KeyboardInterrupt:
            console.print("\n[dim](interrupted)[/dim]")
        except Exception as e:
            console.print(f"[red][error][/red] {type(e).__name__}: {e}")