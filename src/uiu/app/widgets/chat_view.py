"""ChatView: the scrollable message area.

Renders user / assistant / tool / notice rows as child widgets inside a
VerticalScroll. The assistant row is a Markdown widget that updates in place as
tokens stream in, giving live rendering while staying cheap — completed rows
are never rebuilt. Auto-follows the bottom unless the user scrolled up.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, Markdown, Static


class Bubble(Widget):
    """A single message row: role label + content, styled per role."""

    def __init__(self, role: str, text: str, *, agent_name: str = "agent") -> None:
        super().__init__()
        self.role = role
        self.agent_name = agent_name
        self._text = text
        self._tool_rows: list[str] = []

    def compose(self) -> ComposeResult:
        yield Markdown(self._text, id="md-body")

    def update_content(self, text: str) -> None:
        self._text = text
        body = self.query_one("#md-body", Markdown)
        body.update(text)

    def get_text(self) -> str:
        return self._text


class ChatView(VerticalScroll):
    """Scrollable list of message bubbles (chat layout)."""

    class SuggestionPicked(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text


    DEFAULT_CSS = """
    ChatView {
        background: $surface;
    }
    ChatView Bubble {
        width: 100%;
        margin: 0 0 1 0;
        padding: 1 2;
    }
    ChatView Bubble.-user {
        background: $primary 18%;
        border: round $primary;
    }
    ChatView Bubble.-assistant {
        background: $surface-lighten-1;
        border: round $accent;
    }
    ChatView Bubble.-notice {
        background: transparent;
        border: none;
        color: $text-muted;
        padding: 0 1;
    }
    ChatView Bubble.-error {
        background: $error 15%;
        border: round $error;
    }
    ChatView #empty-hint {
        height: auto;
        margin: 2 2;
        color: $text-muted;
    }
    ChatView #empty-hint .hint-title {
        margin: 0 0 1 0;
        color: $text-muted;
    }
    ChatView Button.suggestion-chip {
        margin: 0 1 1 0;
        min-width: 22;
    }
    """

    def __init__(self, agent_name: str = "agent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self._stick = True
        self._active: Bubble | None = None

    async def on_mount(self) -> None:
        await self.show_empty_hint()

    def _mk_bubble(self, role: str, text: str) -> Bubble:
        b = Bubble(role, text, agent_name=self.agent_name)
        if role in ("user", "assistant", "notice", "error"):
            b.set_classes("-" + role)
        return b

    SUGGESTIONS: list[str] = [
        "帮我看看磁盘和内存占用",
        "列出我有哪些技能",
        "帮我写一个问候语 skill",
        "解释一下这个项目怎么用",
    ]

    async def show_empty_hint(self) -> None:
        if self.query("#empty-hint"):
            return
        container = VerticalScroll(id="empty-hint")
        await self.mount(container)
        await container.mount(Label("还没有对话，选一个开始：", classes="hint-title"))
        row = Horizontal()
        await container.mount(row)
        for text in self.SUGGESTIONS:
            await row.mount(Button(text, classes="suggestion-chip"))
        self._stick = True

    async def clear_chat(self) -> None:
        for child in list(self.children):
            await child.remove()
        self._active = None
        await self.show_empty_hint()

    async def _remove_empty_hint(self) -> None:
        for child in list(self.children):
            if child.id == "empty-hint":
                await child.remove()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.has_class("suggestion-chip"):
            self.post_message(self.SuggestionPicked(event.button.label.plain))
            event.stop()

    async def add_user(self, text: str) -> None:
        await self._remove_empty_hint()
        b = self._mk_bubble("user", text)
        await self.mount(b)
        await self._auto_scroll()

    async def add_notice(self, text: str) -> None:
        await self._remove_empty_hint()
        await self.mount(self._mk_bubble("notice", text))
        await self._auto_scroll()

    async def add_error(self, message: str) -> None:
        await self._remove_empty_hint()
        await self.mount(self._mk_bubble("error", message))
        await self._auto_scroll()

    async def begin_assistant(self) -> None:
        """Start a streaming assistant bubble (markdown)."""
        await self._remove_empty_hint()
        self._active = self._mk_bubble("assistant", "")
        await self.mount(self._active)
        await self._auto_scroll()

    async def stream(self, delta: str) -> None:
        if self._active is None:
            await self.begin_assistant()
        assert self._active is not None
        self._active.update_content((self._active.get_text() or "") + delta)
        await self._auto_scroll()

    async def finish_assistant(self) -> None:
        self._active = None
        await self._auto_scroll()

    async def add_tool(self, name: str, ok: bool, preview: str) -> None:
        """Append a tool-invocation row (as a compact notice bubble)."""
        await self._remove_empty_hint()
        icon = "✓" if ok else "✗"
        line = f"{icon} {name}" + (f"  — {preview}" if preview else "")
        await self.mount(self._mk_bubble("notice", "`" + line + "`"))
        await self._auto_scroll()

    async def _auto_scroll(self) -> None:
        if self._stick:
            try:
                await self.scroll_end(animate=False)
            except Exception:
                pass

    def _on_scroll_up(self) -> None:
        self._stick = False

    def _on_scroll_down(self) -> None:
        self._stick = True

    def on_mouse_scroll_up(self, event: Any) -> None:
        self._stick = False

    def on_mouse_scroll_down(self, event: Any) -> None:
        self._stick = True