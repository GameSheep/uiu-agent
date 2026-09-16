"""SideBar: 可折叠侧栏（会话 / 视图 / 信息 + 本次会话统计）。"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Label, Static

from ..theme import glyph

ACTION_PALETTE = "__action__:palette"
ACTION_THEME = "__action__:theme"
ACTION_HELP = "__action__:help"
ACTION_SESSIONS = "__action__:sessions"
ACTION_SESSION_PREFIX = "__session__:"

RECENT_LIMIT = 4


class SideBar(VerticalScroll):
    """Collections of quick actions and slash commands."""

    class CommandPicked(Message):
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    DEFAULT_CSS = """
    SideBar {
        width: 32;
        background: $panel;
        border-right: solid $panel-lighten-1;
        padding: 0 1 1 1;
        scrollbar-size-vertical: 1;
    }
    SideBar .section-title {
        color: $accent;
        text-style: bold;
        margin: 1 0 0 0;
        height: 1;
    }
    SideBar Button {
        width: 100%;
        min-width: 0;
        height: 1;
        margin: 0;
        padding: 0 1;
        border: none !important;
        background: transparent !important;
        color: $text;
        content-align: left middle;
        text-align: left;
    }
    SideBar Button:hover {
        background: $panel-lighten-1 !important;
    }
    SideBar Button:focus {
        background: $primary 45% !important;
        color: $text !important;
    }
    SideBar #side-stats {
        margin: 0 0 0 0;
        padding: 0 1;
        color: $text-muted;
        height: auto;
    }
    SideBar #side-recent {
        height: auto;
    }
    SideBar #side-recent .side-empty {
        color: $text-muted;
        height: 1;
        padding: 0 1;
    }
    """

    SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
        ("会话", [
            ("新会话", "/new", "Ctrl+N"),
            ("切换会话", "/sessions", "Ctrl+X"),
            ("保存会话", "/save", ""),
            ("压缩旧对话", "/compact", ""),
        ]),
        ("视图", [
            ("命令面板", ACTION_PALETTE, "Ctrl+E"),
            ("切换主题", ACTION_THEME, "Ctrl+T"),
            ("帮助", ACTION_HELP, "F1"),
        ]),
        ("信息", [
            ("状态", "/status", ""),
            ("会话用量", "/usage", "Ctrl+U"),
            ("自动化建议", "/suggestions", ""),
        ]),
    ]

    # 兼容旧引用
    QUICK: list[str] = ["/new", "/save", "/sessions", "/compact", "/status", "/help"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._buttons: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Label("最近会话", classes="section-title")
        self._recent_box = Vertical(id="side-recent")
        yield self._recent_box
        yield Button("全部会话…  [dim]Ctrl+X[/dim]", id="side-all-sessions")
        self._buttons["side-all-sessions"] = ACTION_SESSIONS
        yield Label("本次会话", classes="section-title")
        yield Static("", id="side-stats")
        for title, items in self.SECTIONS:
            yield Label(title, classes="section-title")
            for i, (label, command, key) in enumerate(items):
                text = label if not key else f"{label}  [dim]{key}[/dim]"
                bid = f"side-{abs(hash((title, command, i))) % 100000}"
                self._buttons[bid] = command
                yield Button(text, id=bid)

    async def update_recent(self, sessions: list[dict], current: str = "") -> None:
        """List the most recent other sessions as one-click switches."""
        try:
            box = self.query_one("#side-recent", Vertical)
        except Exception:
            return
        await box.remove_children()
        others = [s for s in (sessions or []) if str(s.get("id")) != current]
        others = others[:RECENT_LIMIT]
        if not others:
            await box.mount(Static("（暂无其他会话）", classes="side-empty"))
            return
        for s in others:
            sid = str(s.get("id"))
            bid = f"rec-{abs(hash(sid)) % 100000}"
            self._buttons[bid] = ACTION_SESSION_PREFIX + sid
            hint = self._ago(float(s.get("updated") or 0))
            label = f"{sid}  [dim]{hint}[/dim]" if hint else sid
            await box.mount(Button(label, id=bid))

    @staticmethod
    def _ago(updated: float) -> str:
        import time as _t
        if not updated:
            return ""
        delta = max(0, int(_t.time() - updated))
        if delta < 60:
            return "刚刚"
        if delta < 3600:
            return f"{delta // 60}m"
        if delta < 86400:
            return f"{delta // 3600}h"
        return f"{delta // 86400}d"

    async def update_stats(self, *, turns: int = 0, tools: int = 0,
                           ctx_pct: int = 0, session: str = "default") -> None:
        try:
            block = self.query_one("#side-stats", Static)
        except Exception:
            return
        block.update(
            f"  {session}  " + glyph("sep") + f"  {turns} 轮\n"
            f"  tools {tools}  " + glyph("sep") + f"  ctx {ctx_pct}%"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        command = self._buttons.get(event.button.id or "")
        if command:
            self.post_message(self.CommandPicked(command))
            event.stop()
