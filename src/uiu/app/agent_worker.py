"""Bridge that runs the existing agent.run_turn on a worker thread.

The textual app must stay responsive while the LLM streams. We therefore run
run_turn on a plain thread (thread=True via App.run_worker) and translate its
callbacks into textual Message objects delivered on the event loop.

Interruption: setting `cancel` asks the LLM stream to stop at the next safe
point (the run_turn engine checks cancellation between chunks where supported;
we also simply drop remaining output and mark the turn interrupted).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

# A non-transient marker raised from the streaming callback to abort an LLM
# round-trip when the user hits Esc. run_turn's retry logic does not classify
# it as transient or context overflow, so it propagates cleanly out of run_turn.
class _Cancelled(Exception):
    pass

from .messages import (
    Interrupted,
    NoticeEvent,
    TextChunk,
    ThoughtChunk,
    ToolCallEvent,
    ToolResultEvent,
    TurnDone,
    TurnError,
)


def agent_turn(
    *,
    client: Any,
    messages: list[dict],
    tool_schemas: list[dict],
    skills: list | None,
    model: str,
    cfg: Any,
    emit: Callable[[object], None],
    cancel: threading.Event,
) -> None:
    """Run one turn and emit() textual Message objects from the thread."""
    from ..agent import run_turn
    from ..learning import register_memory_hook  # noqa: F401  (kept hot reload pattern parity)

    started = time.monotonic()

    def on_thought(delta: str) -> None:
        if cancel.is_set():
            raise _Cancelled()
        if delta:
            emit(ThoughtChunk(delta))

    def on_text(delta: str) -> None:
        if cancel.is_set():
            raise _Cancelled()
        if delta:
            emit(TextChunk(delta))

    def on_tool_call(name: str, args: dict) -> None:
        if not cancel.is_set():
            emit(ToolCallEvent(name, args))

    def on_tool_result(name: str, result: str) -> None:
        if not cancel.is_set():
            emit(ToolResultEvent(name, result))

    def on_notice(text: str) -> None:
        if not cancel.is_set():
            emit(NoticeEvent(text))

    try:
        final = run_turn(
            client=client,
            messages=messages,
            tool_schemas=tool_schemas,
            skills=skills,
            model=model,
            cfg=cfg,
            on_text=on_text,
            on_thought=on_thought,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_notice=on_notice,
        )
        elapsed = time.monotonic() - started
        if cancel.is_set():
            emit(Interrupted())
        else:
            emit(TurnDone(final or "", elapsed))
    except _Cancelled:
        emit(Interrupted())
    except Exception as e:  # noqa: BLE001 - report any engine failure to UI
        if cancel.is_set():
            emit(Interrupted())
        else:
            emit(TurnError(e))
