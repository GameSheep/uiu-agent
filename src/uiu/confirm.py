"""Host confirmation hook for sensitive tools.

Certain tools (send_wechat, shutdown, macro_play) should never fire without a
human in the loop. The agent engine calls them synchronously from the worker
thread; the host (TUI / gateway) registers a blocking confirm handler here so
those tools hard-stop and ask the user before executing.

No handler registered => the tool runs as-is (CLI / tests), preserving current
behavior for callers that already gate elsewhere.
"""

from __future__ import annotations

from typing import Callable

# tool names that must be confirmed by the user before execution
CONFIRM_TOOLS: frozenset[str] = frozenset({"send_wechat", "shutdown", "macro_play"})

_confirm: Callable[[str, str], str] | None = None


def set_confirm_handler(fn: Callable[[str, str], str] | None) -> None:
    """Register host confirm callback: fn(tool_name, args_preview) -> "yes"/"no"."""
    global _confirm
    _confirm = fn


def needs_confirm(name: str) -> bool:
    return name in CONFIRM_TOOLS and _confirm is not None


def confirm(name: str, args_json: str) -> str:
    """Ask the host; returns "yes" (proceed) or "no" (block with a message)."""
    if _confirm is None:
        return "yes"
    try:
        preview = " ".join((args_json or "").split())[:200]
    except Exception:
        preview = ""
    answer = (_confirm(name, preview) or "no").strip().lower()
    if answer in ("yes", "y", "ok", "confirm", "1"):
        return "yes"
    return "no"
