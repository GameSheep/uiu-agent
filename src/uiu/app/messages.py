"""Custom Message events bridging the agent worker thread and the textual UI.

The agent `run_turn` runs on a worker thread. It reports progress through the
`on_text` / `on_tool_call` / `on_tool_result` / `on_notice` callbacks, which the
worker adapts to post_message() calls. These Message subclasses are delivered on
the event loop so the UI can render streaming output without blocking.
"""

from __future__ import annotations

from textual.message import Message

__all__ = [
    "ThoughtChunk",
    "TextChunk",
    "ToolCallEvent",
    "ToolResultEvent",
    "NoticeEvent",
    "TurnDone",
    "TurnError",
    "Interrupted",
]


class ThoughtChunk(Message):
    """A token (or slice) of assistant thinking/reasoning text."""

    def __init__(self, delta: str) -> None:
        super().__init__()
        self.delta = delta


class TextChunk(Message):
    """A token (or buffered slice) of assistant text."""

    def __init__(self, delta: str) -> None:
        super().__init__()
        self.delta = delta


class ToolCallEvent(Message):
    """A tool is about to run."""

    def __init__(self, name: str, arguments: dict) -> None:
        super().__init__()
        self.name = name
        self.arguments = arguments


class ToolResultEvent(Message):
    """A tool finished and returned a result."""

    def __init__(self, name: str, result: str) -> None:
        super().__init__()
        self.name = name
        self.result = result


class NoticeEvent(Message):
    """A dim, non-user-facing notice (retry/compact)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class TurnDone(Message):
    """The agent turn finished successfully."""

    def __init__(self, final_text: str, elapsed: float) -> None:
        super().__init__()
        self.final_text = final_text
        self.elapsed = elapsed


class TurnError(Message):
    """The agent turn raised an error."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error


class Interrupted(Message):
    """The agent turn was interrupted by the user (Esc)."""