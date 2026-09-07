"""UiuApp: full-screen textual application for uiu agent conversations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from .. import __version__, tools as _tools
from ..agent import run_turn
from ..workspace import Workspace, load_workspace

from .messages import (
    Interrupted,
    NoticeEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
    TurnDone,
    TurnError,
)
from .widgets import ChatView, Composer, HeaderBar, SideBar, StatusBar


class HelpModal(ModalScreen[None]):
    """Overlay listing slash commands and shortcuts (/?)."""

    def __init__(self, help_text: str) -> None:
        super().__init__()
        self._help = help_text

    def compose(self) -> ComposeResult:
        from textual.widgets import Markdown
        with Vertical(id="help-box"):
            yield Static("帮助 — Esc 关闭", classes="help-title");
            yield Markdown(self._help);
            yield Button("关闭 (Esc)", id="help-close", variant="primary");

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-box {
        width: 70%;
        height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #help-box .help-title {
        text-style: bold;
        color: $accent;
    }
    """

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss(None)

    def on_mount(self) -> None:
        self.query_one("#help-close", Button).focus()

    def _on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        else:
            super()._on_key(event)


class ConfirmModal(ModalScreen[bool]):
    """Inline confirmation for sensitive actions (send_wechat etc.)."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self.message, classes="confirm-text");
            with Horizontal():
                yield Button("确认", id="confirm-yes", variant="error");
                yield Button("取消", id="confirm-no", variant="primary");

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-box {
        width: 60;
        padding: 2 3;
        border: round $error;
        background: $surface;
    }
    #confirm-box Button {
        margin: 1 1 0 0;
    }
    """

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-yes":
            self.dismiss(True)
        elif event.button.id == "confirm-no":
            self.dismiss(False)

    def _on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss(False)
            event.stop()
        else:
            super()._on_key(event)