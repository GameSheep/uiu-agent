"""SideBar: collapsible panel with session actions and quick slash commands."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static


class SideBar(VerticalScroll):
    """Collections of quick actions and slash commands."""

    class CommandPicked(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    DEFAULT_CSS = """
    SideBar {
        width: 30;
        background: $surface;
        border-right: solid $primary;
        padding: 0 1;
    }
    SideBar Label.-title {
        color: $accent;
        text-style: bold;
        margin: 1 0 1 0;
    }
    SideBar Button {
        width: 100%;
        margin: 0 0 1 0;
    }
    """

    QUICK: list[str] = [
        "/new 新会话",
        "/save 保存会话",
        "/sessions 会话列表",
        "/compact 压缩旧对话",
        "/status 状态",
        "/help 帮助",
    ]

    def compose(self) -> ComposeResult:
        yield Label("会话", classes="title");
        for text in self.QUICK:
            yield Button(text, id="cmd-" + text.split()[0].lstrip("/"))
        yield Static("（可折叠：ctrl+s）", classes="title");

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button;
        for text in self.QUICK:
            if btn.id == "cmd-" + text.split()[0].lstrip("/"):
                self.post_message(self.CommandPicked(text.split()[0]));
                event.stop();
                return;