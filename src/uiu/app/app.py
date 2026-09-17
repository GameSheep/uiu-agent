"""UiuApp: full-screen textual application for uiu agent conversations."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Markdown, Static

from .. import __version__ as _VERSION
from .. import tools as _tools
from ..workspace import Workspace

from .agent_worker import agent_turn
from .clarify_bridge import AskUser, ClarifyBridge
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
from .theme import (
    DEFAULT_THEME,
    THEMES,
    glyph,
    palette,
    palette_from_config,
    register_themes,
    theme_names,
)
from .widgets import (
    ChatView,
    Composer,
    HeaderBar,
    OutputRow,
    SideBar,
    StatusBar,
    ToolRow,
)

# --------------------------------------------------------------------------
# Overlays
# --------------------------------------------------------------------------


class HelpModal(ModalScreen[None]):
    """Categorized help overlay: section list on the left, content on the right."""

    def __init__(self, sections: dict[str, str]) -> None:
        super().__init__()
        self._sections = sections or {"帮助": "（暂无内容）"}
        self._names = list(self._sections)

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static(self._title(), classes="modal-title")
            with Horizontal(id="help-body"):
                yield ListView(
                    *[ListItem(Label(name)) for name in self._names],
                    id="help-nav",
                )
                yield Markdown(self._sections[self._names[0]], id="help-md")
            yield Static(
                "↑↓ 切换分类  " + glyph("sep") + "  Esc / F1 关闭  "
                + glyph("sep") + "  对话里输入 /help 也能看全部命令",
                classes="modal-foot",
            )

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("uiu 帮助", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
        background: $background 60%;
    }
    #help-box {
        width: 86%;
        height: 84%;
        border: round $primary 55%;
        background: $panel;
        padding: 0 1;
    }
    #help-box .modal-title {
        height: 1;
        text-style: bold;
        padding: 0 1;
    }
    #help-body {
        height: 1fr;
    }
    #help-nav {
        width: 24;
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0 1 0 0;
    }
    #help-nav ListItem {
        padding: 0 1;
        background: transparent;
    }
    #help-nav ListItem.-highlight {
        background: $primary 45%;
    }
    #help-md {
        width: 1fr;
        height: 1fr;
        background: transparent;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    #help-box .modal-foot {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("f1", "close", "Close", show=False),
        Binding("tab", "focus_nav", "Next", show=False, priority=True),
    ]

    def on_mount(self) -> None:
        nav = self.query_one("#help-nav", ListView)
        nav.index = 0
        nav.focus()

    async def on_list_view_highlighted(self, event: Any) -> None:
        lv = getattr(event, "list_view", None)
        if lv is not None and lv.id != "help-nav":
            return
        idx = getattr(event, "item_index", None)
        if idx is None:
            idx = self.query_one("#help-nav", ListView).index or 0
        if 0 <= idx < len(self._names):
            self.query_one("#help-md", Markdown).update(self._sections[self._names[idx]])

    def action_close(self) -> None:
        self.dismiss(None)

    def action_focus_nav(self) -> None:
        self.query_one("#help-nav", ListView).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss(None)


class ConfirmModal(ModalScreen[str]):
    """Inline confirmation modal (sensitive actions / clarify choices)."""

    def __init__(self, question: str, options: list[str] | None = None) -> None:
        super().__init__()
        self.question = question
        self.options = options or []

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._title(), classes="modal-title")
            yield Static(self.question, classes="confirm-text")
            if self.options:
                for i, opt in enumerate(self.options[:6], 1):
                    yield Button(f"{i}. {opt}", id=f"opt-{i}", classes="opt-btn")
            else:
                with Horizontal(classes="opt-row"):
                    yield Button("确认", id="opt-yes", variant="error")
                    yield Button("取消", id="opt-no", variant="primary")
            yield Static("Esc 取消", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.warning}")
        t.append("需要确认", style=f"bold {pal.foreground}")
        return t

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
        background: $background 60%;
    }
    #confirm-box {
        width: 68;
        max-width: 90%;
        height: auto;
        padding: 0 2 1 2;
        border: round $warning 65%;
        background: $panel;
    }
    #confirm-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #confirm-box .confirm-text {
        margin: 1 0;
        height: auto;
    }
    #confirm-box .opt-btn {
        width: 100%;
        height: 1;
        border: none;
        background: $panel-lighten-1;
        color: $text;
        margin: 0 0 1 0;
    }
    #confirm-box .opt-btn:hover {
        background: $warning 40%;
    }
    #confirm-box .opt-row Button {
        margin: 0 1 0 0;
    }
    #confirm-box .modal-foot {
        height: 1;
        color: $text-muted;
    }
    """

    def _answer(self, text: str) -> None:
        self.dismiss(text)

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def action_close(self) -> None:
        self.dismiss("")

    async def _on_key(self, event: Any) -> None:
        if self.options and event.key.isdigit():
            n = int(event.key)
            if 1 <= n <= len(self.options):
                self._answer(self.options[n - 1])
            event.stop()
            return
        await super()._on_key(event)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("opt-"):
            idx = bid[len("opt-"):]
            if idx == "yes":
                self._answer("yes")
            elif idx == "no":
                self._answer("no")
            elif idx.isdigit():
                n = int(idx)
                if 1 <= n <= len(self.options):
                    self._answer(self.options[n - 1])
                else:
                    self._answer("")


class ThemePicker(ModalScreen[str]):
    """Theme chooser with live preview while the highlight moves."""

    def __init__(self, current: str, note: str = "") -> None:
        super().__init__()
        self.current = current
        self._names = theme_names()
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-box"):
            yield Static(self._title(), classes="modal-title")
            items = []
            for name in self._names:
                p = THEMES[name]
                mark = glyph("dot") if name == self.current else " "
                items.append(
                    ListItem(Label(f"{mark} {p.label}   [dim]{p.tagline}[/dim]"),
                             id=f"theme-{name}")
                )
            yield ListView(*items, id="theme-list")
            if self.note:
                yield Static(self.note, classes="modal-note")
            yield Static("↑↓ 预览  " + glyph("sep") + "  Enter 应用  "
                         + glyph("sep") + "  Esc 取消", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("主题", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    ThemePicker {
        align: center middle;
        background: $background 60%;
    }
    #theme-box {
        width: 64;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        border: round $accent 60%;
        background: $panel;
        padding: 0 1 1 1;
    }
    #theme-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #theme-list {
        height: auto;
        max-height: 12;
        background: transparent;
        border: none;
    }
    #theme-list ListItem {
        padding: 0 1;
        background: transparent;
    }
    #theme-list ListItem.-highlight {
        background: $accent 35%;
    }
    #theme-box .modal-note {
        height: auto;
        color: $accent;
        margin: 1 0 0 0;
    }
    #theme-box .modal-foot {
        height: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def on_mount(self) -> None:
        lv = self.query_one("#theme-list", ListView)
        try:
            lv.index = self._names.index(self.current)
        except ValueError:
            lv.index = 0
        lv.focus()

    def _preview(self, idx: int) -> None:
        if 0 <= idx < len(self._names):
            try:
                self.app.theme = self._names[idx]
            except Exception:
                pass

    async def on_list_view_highlighted(self, event: Any) -> None:
        idx = getattr(event, "item_index", None)
        if idx is None:
            idx = self.query_one("#theme-list", ListView).index
        if idx is not None:
            self._preview(idx)

    async def on_list_view_selected(self, event: Any) -> None:
        lv = self.query_one("#theme-list", ListView)
        idx = lv.index if lv.index is not None else 0
        if 0 <= idx < len(self._names):
            self.dismiss(self._names[idx])
        else:
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss("")


class InfoPanel(ModalScreen[None]):
    """通用信息浮层：右对齐标签 + 值，Esc/Enter 关闭。"""

    def __init__(self, title: str, rows_fn: Callable[[], list[tuple[str, Any]]], *,
                 body_id: str = "info-body", footer: str = "") -> None:
        super().__init__()
        self.panel_title = title
        self._rows_fn = rows_fn
        self.body_id = body_id
        self.footer = footer

    def compose(self) -> ComposeResult:
        with Vertical(id="info-box"):
            yield Static(self._title(), classes="modal-title")
            yield Static(self._body(), id=self.body_id, classes="info-body")
            yield Static(self.footer or "Esc / Enter 关闭", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append(self.panel_title, style=f"bold {pal.primary}")
        return t

    @staticmethod
    def meter(pal: Any, pct: int, cells: int = 24) -> Text:
        filled = max(0, min(cells, round(pct / 100 * cells)))
        color = pal.success
        if pct >= 80:
            color = pal.error
        elif pct >= 55:
            color = pal.warning
        out = Text()
        out.append("█" * filled, style=color)
        out.append("░" * (cells - filled), style=pal.boost)
        return out

    def _body(self) -> Table:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(justify="right", style="dim", no_wrap=True)
        grid.add_column(justify="left", no_wrap=False)
        for label, value in self._rows_fn():
            grid.add_row(label, value if not isinstance(value, str) else Text(value))
        return grid

    DEFAULT_CSS = """
    InfoPanel {
        align: center middle;
        background: $background 60%;
    }
    #info-box {
        width: 68;
        max-width: 92%;
        height: auto;
        border: round $primary 55%;
        background: $panel;
        padding: 0 2 1 2;
    }
    #info-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #info-box .info-body {
        height: auto;
        padding: 1 0;
    }
    #info-box .modal-foot {
        height: auto;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close", show=False),
    ]

    def action_close(self) -> None:
        self.dismiss(None)


class UsageModal(InfoPanel):
    """会话用量面板（/usage、Ctrl+U）。"""

    def __init__(self, stats: dict[str, Any]) -> None:
        super().__init__(
            "会话用量",
            self._build_rows,
            body_id="usage-body",
            footer="Esc / Enter 关闭  " + glyph("sep") + "  /clear 清空  "
                   + glyph("sep") + "  /compact 压缩",
        )
        self.stats = stats or {}

    def _build_rows(self) -> list[tuple[str, Any]]:
        pal = palette(self.app)
        s = self.stats
        rows: list[tuple[str, Any]] = [
            ("模型", Text(str(s.get("model") or "-"), style=pal.secondary)),
            ("agent", Text(str(s.get("agent") or "-"), style=f"bold {pal.foreground}")),
            ("会话", Text(str(s.get("session") or "default"), style=pal.accent)),
            ("轮数", Text(str(s.get("turns", 0)))),
        ]
        pct = int(s.get("pct", 0))
        meter = self.meter(pal, pct)
        meter.append(f"  {pct}%", style="dim")
        rows.append(("上下文", meter))
        rows.append(("估算 token", Text(f"≈{s.get('tokens', 0):,} / ~30k", style=pal.foreground)))
        rows.append(("消息", Text(f"{s.get('user_msgs', 0)} 条用户 · "
                                  f"{s.get('asst_msgs', 0)} 条回复")))
        rows.append(("工具 / 技能", Text(f"{s.get('tools', 0)} 个工具 · "
                                        f"{s.get('skills', 0)} 个技能")))
        rows.append(("已存会话", Text(str(s.get("saved", 0)))))
        rows.append(("工作区", Text(str(s.get("workspace") or "-"), style="dim")))
        return rows


class StatusModal(InfoPanel):
    """运行状态面板（/status）：配置与连通性一眼看完。"""

    def __init__(self, stats: dict[str, Any]) -> None:
        super().__init__(
            "运行状态",
            self._build_rows,
            body_id="status-body",
            footer="Esc / Enter 关闭  " + glyph("sep") + "  Ctrl+U 会话用量  "
                   + glyph("sep") + "  uiu doctor 体检",
        )
        self.stats = stats or {}

    def _build_rows(self) -> list[tuple[str, Any]]:
        pal = palette(self.app)
        s = self.stats
        key_ok = bool(s.get("api_key"))
        key_style = pal.success if key_ok else pal.error
        key_text = ("✓ 已配置" if key_ok else "✗ 未配置") + f"  ({s.get('api_key_env') or '-'})"
        rows: list[tuple[str, Any]] = [
            ("agent", Text(str(s.get("agent") or "-"), style=f"bold {pal.primary}")),
            ("模型", Text(str(s.get("model") or "-"), style=pal.secondary)),
            ("base_url", Text(str(s.get("base_url") or "(provider 默认)"), style="dim")),
            ("api_mode", Text(str(s.get("api_mode") or "-"))),
            ("API key", Text(key_text, style=key_style)),
            ("渠道", Text(str(s.get("channels") or "0 启用 / 0 配置"))),
            ("MCP", Text(str(s.get("mcp") or 0))),
            ("工具 / 技能", Text(f"{s.get('tools', 0)} 个工具 · {s.get('skills', 0)} 个技能")),
            ("会话", Text(f"{s.get('session') or 'default'} · {s.get('turns', 0)} 轮", style=pal.accent)),
            ("已存会话", Text(str(s.get("saved", 0)))),
            ("主题", Text(str(s.get("theme") or "-"))),
            ("版本", Text("v" + str(s.get("version") or "-"))),
            ("工作区", Text(str(s.get("workspace") or "-"), style="dim")),
        ]
        return rows


class SessionSwitcher(ModalScreen[str]):
    """已存会话切换器：↑↓ 选择、Enter 载入、d 删除（Hermes Ctrl+X 风格）。"""

    def __init__(self, workspace: Any, current: str) -> None:
        super().__init__()
        self.workspace = workspace
        self.current = current or "default"
        self._sessions: list[dict] = []

    def _load(self) -> list[dict]:
        try:
            from .. import sessions as _sessions
            return _sessions.list_sessions(self.workspace)
        except Exception:
            return []

    def compose(self) -> ComposeResult:
        with Vertical(id="session-box"):
            yield Static(self._title(), classes="modal-title")
            yield ListView(id="session-list")
            yield Static("↑↓ 选择  " + glyph("sep") + "  Enter 载入  " + glyph("sep")
                         + "  d 删除  " + glyph("sep") + "  Esc 关闭", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("切换会话", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    SessionSwitcher {
        align: center middle;
        background: $background 60%;
    }
    #session-box {
        width: 74;
        max-width: 92%;
        height: auto;
        max-height: 80%;
        border: round $accent 60%;
        background: $panel;
        padding: 0 1 1 1;
    }
    #session-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #session-list {
        height: auto;
        max-height: 14;
        background: transparent;
        border: none;
    }
    #session-list ListItem {
        padding: 0 1;
        background: transparent;
    }
    #session-list ListItem.-highlight {
        background: $accent 35%;
    }
    #session-box .modal-foot {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    """

    async def on_mount(self) -> None:
        await self.reload_sessions()

    async def reload_sessions(self) -> None:
        from textual.widgets import ListItem
        self._sessions = self._load()
        lv = self.query_one("#session-list", ListView)
        await lv.clear()
        if not self._sessions:
            await lv.append(ListItem(Label("（还没有已保存的会话）")))
            lv.focus()
            return
        for i, s in enumerate(self._sessions):
            mark = glyph("dot") if s["id"] == self.current else " "
            desc = Label(f"{mark} {s['id']}   [dim]{s.get('turns', 0)} 轮[/dim]")
            await lv.append(ListItem(desc))
        idx = next((i for i, s in enumerate(self._sessions)
                    if s["id"] == self.current), 0)
        lv.index = idx
        lv.focus()

    async def on_list_view_selected(self, event: Any) -> None:
        lv = self.query_one("#session-list", ListView)
        idx = lv.index if lv.index is not None else 0
        if self._sessions and 0 <= idx < len(self._sessions):
            self.dismiss(self._sessions[idx]["id"])
        else:
            self.dismiss("")

    async def action_delete(self) -> None:
        lv = self.query_one("#session-list", ListView)
        idx = lv.index if lv.index is not None else -1
        if not (0 <= idx < len(self._sessions)):
            return
        sid = self._sessions[idx]["id"]
        if sid == self.current:
            return
        try:
            from .. import sessions as _sessions
            meta = _sessions.remove_session_ex(self.workspace, sid)
            if meta:
                # 让 App 记住这条回收站条目：Ctrl+Z 一键撤销
                try:
                    self.app._last_trash_id = str(meta.get("id", ""))
                except Exception:
                    pass
        except Exception:
            pass
        await self.reload_sessions()

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("d", "delete", "Delete"),
        # 列表为空时 ListView 没有游标，Enter 会被它吞掉 —— 这里兜底
        Binding("enter", "choose", "Open", show=False, priority=True),
    ]

    async def action_choose(self) -> None:
        await self.on_list_view_selected(None)

    def action_cancel(self) -> None:
        self.dismiss("")


def _esc_markup(text: str) -> str:
    """Escape Rich markup so user content can't break the label."""
    return str(text).replace("[", r"[")


def _markup_highlight(text: str, query: str) -> str:
    """Escape *text* and bold the first case-insensitive hit of *query*."""
    text = str(text)
    if not query:
        return _esc_markup(text)
    low = text.lower()
    i = low.find(query.lower())
    if i < 0:
        return _esc_markup(text)
    j = i + len(query)
    return (_esc_markup(text[:i]) + "[b]" + _esc_markup(text[i:j]) + "[/b]"
            + _esc_markup(text[j:]))


class SessionSearchModal(ModalScreen[Any]):
    """跨会话关键词检索：输入即搜（无语义模型，毫秒级），Enter 打开命中的会话。"""

    DEBOUNCE = 0.25

    def __init__(self, workspace: Any, query: str = "", limit: int = 20) -> None:
        super().__init__()
        self.workspace = workspace
        # 注意别叫 self.query —— 会覆盖 Widget.query()（DOM 查询方法）
        self.initial_query = query or ""
        self.limit = limit
        self._hits: list[dict] = []
        self._timer: Any = None

    def compose(self) -> ComposeResult:
        with Vertical(id="searchall-box"):
            yield Static(self._title(), classes="modal-title")
            yield Input(value=self.initial_query, placeholder="搜索所有已保存会话…",
                        id="searchall-input")
            yield ListView(id="searchall-list")
            yield Static("输入即搜  " + glyph("sep") + "  ↑↓ 选择  " + glyph("sep")
                         + "  Enter 打开会话  " + glyph("sep") + "  Esc 关闭",
                         classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("检索会话", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    SessionSearchModal {
        align: center middle;
        background: $background 60%;
    }
    #searchall-box {
        width: 90;
        max-width: 94%;
        height: auto;
        max-height: 80%;
        border: round $accent 60%;
        background: $panel;
        padding: 0 1 1 1;
    }
    #searchall-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #searchall-box Input {
        height: 1;
        margin: 0 0 1 0;
        padding: 0 1;
        border: none;
        background: $panel-lighten-2;
    }
    #searchall-list {
        height: auto;
        max-height: 14;
        background: transparent;
        border: none;
    }
    #searchall-list ListItem {
        height: auto;
        padding: 0 1;
        background: transparent;
    }
    #searchall-list ListItem.-highlight {
        background: $accent 35%;
    }
    #searchall-list .hit {
        height: auto;
    }
    #searchall-list .hit-head {
        height: 1;
    }
    #searchall-list .hit-ctx {
        color: $text-muted;
        height: auto;
    }
    #searchall-box .modal-foot {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    """

    async def on_mount(self) -> None:
        self.query_one("#searchall-input", Input).focus()
        await self.run_search()

    def on_input_changed(self, event: Any) -> None:
        self._schedule()

    def _schedule(self) -> None:
        try:
            if self._timer is not None:
                self._timer.stop()
            self._timer = self.set_timer(self.DEBOUNCE, self._fire)
        except Exception:
            pass

    def _fire(self) -> None:
        self._timer = None
        try:
            self.run_worker(self.run_search(), exclusive=False)
        except Exception:
            pass

    async def run_search(self) -> None:
        from textual.widgets import ListItem
        q = (self.query_one("#searchall-input", Input).value or "").strip()
        try:
            from .. import sessions as _sessions
            hits = _sessions.search_sessions(self.workspace, q, self.limit) if q else []
        except Exception:
            hits = []
        self._hits = hits
        lv = self.query_one("#searchall-list", ListView)
        await lv.clear()
        if not q:
            await lv.append(ListItem(Label("输入关键词开始检索（跨所有已存会话）")))
            return
        if not hits:
            await lv.append(ListItem(Label("（没有命中）")))
            return
        for h in hits:
            snippet = " ".join(str(h.get("text") or "").split())
            head = (f"[b]{_esc_markup(h.get('session', '?'))}[/b] "
                    f"[dim]{_esc_markup(h.get('role', ''))}[/dim]  ")
            body = _markup_highlight(snippet[:88], q)
            ctx = ""
            for c in (h.get("context") or [])[:1]:
                ctext = " ".join(str(c.get("text") or "").split())
                ctx = f"[dim]({_esc_markup(c.get('role', '?'))}) " \
                      f"{_esc_markup(ctext[:82])}[/dim]"
            inner = Vertical(Label(head + body, classes="hit-head"),
                             *([Label(ctx, classes="hit-ctx")] if ctx else []),
                             classes="hit")
            await lv.append(ListItem(inner))
        lv.index = 0

    async def on_list_view_selected(self, event: Any) -> None:
        lv = self.query_one("#searchall-list", ListView)
        idx = lv.index if lv.index is not None else -1
        if 0 <= idx < len(self._hits):
            self.dismiss(self._hits[idx])
        else:
            self.dismiss(None)

    async def on_input_submitted(self, event: Any) -> None:
        await self.on_list_view_selected(event)

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "choose", "Open", show=False, priority=True),
    ]

    async def action_choose(self) -> None:
        await self.on_list_view_selected(None)

    def action_close(self) -> None:
        self.dismiss(None)


class SearchModal(ModalScreen[int]):
    """在当前对话里搜索（Ctrl+R）：输入关键词 → 命中列表 → Enter 跳转。"""

    SCOPE_ORDER = ("all", "对话", "输出")
    SCOPE_LABEL = {"all": "全部", "对话": "对话", "输出": "命令输出"}

    def __init__(self, entries: list[dict[str, str]]) -> None:
        super().__init__()
        self.entries = entries or []
        self._hits: list[int] = list(range(len(self.entries)))
        self._scope = "all"

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Static(self._title(), classes="modal-title")
            yield Input(placeholder="输入关键词过滤当前对话…", id="search-input")
            yield ListView(id="search-list")
            yield Static("↑↓ 选择  " + glyph("sep") + "  Enter 跳转  " + glyph("sep")
                         + "  Esc 关闭", id="search-foot", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("搜索对话", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    SearchModal {
        align: center middle;
        background: $background 60%;
    }
    #search-box {
        width: 86;
        max-width: 94%;
        height: auto;
        max-height: 80%;
        border: round $primary 55%;
        background: $panel;
        padding: 0 1 1 1;
    }
    #search-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #search-box Input {
        height: 1;
        margin: 0 0 1 0;
        padding: 0 1;
        border: none;
        background: $panel-lighten-2;
    }
    #search-list {
        height: auto;
        max-height: 14;
        background: transparent;
        border: none;
    }
    #search-list ListItem {
        padding: 0 1;
        background: transparent;
    }
    #search-list ListItem.-highlight {
        background: $primary 45%;
    }
    #search-box .modal-foot {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    """

    async def on_mount(self) -> None:
        await self._populate("")
        self.query_one("#search-input", Input).focus()

    async def _populate(self, query: str) -> None:
        from textual.widgets import ListItem
        q = (query or "").strip().lower()
        hits: list[int] = []
        for i, e in enumerate(self.entries):
            if self._scope != "all" and e.get("kind", "对话") != self._scope:
                continue
            if q:
                haystack = (str(e.get("text", "")) + " "
                            + str(e.get("who", ""))).lower()
                if q not in haystack:
                    continue
            hits.append(i)
        self._hits = hits
        lv = self.query_one("#search-list", ListView)
        await lv.clear()
        try:
            foot = self.query_one("#search-foot", Static)
            scope = f"命中 {len(self._hits)} 处" if self._hits else "无命中"
            foot.update(f"范围：{self.SCOPE_LABEL.get(self._scope, self._scope)}  "
                        + glyph("sep") + f"  {scope}  " + glyph("sep")
                        + "  Tab 切范围  " + glyph("sep") + "  ↑↓ 选择  "
                        + glyph("sep") + "  Enter 跳转  " + glyph("sep") + "  Esc 关闭")
        except Exception:
            pass
        if not self._hits:
            await lv.append(ListItem(Label("（没有匹配的消息）")))
            return
        for i in self._hits[:80]:
            e = self.entries[i]
            snippet = " ".join(e.get("text", "").split())
            pos = snippet.lower().find(q) if q else 0
            if pos > 28:
                snippet = "…" + snippet[pos - 20:]
            head = (f"[b]{_esc_markup(e.get('who', '?'))}[/b] "
                    f"[dim]{_esc_markup(e.get('time', ''))}[/dim]  ")
            await lv.append(ListItem(Label(head + _markup_highlight(snippet[:96], q))))
        lv.index = 0

    async def on_input_changed(self, event: Any) -> None:
        await self._populate(self.query_one("#search-input", Input).value or "")

    async def on_input_submitted(self, event: Any) -> None:
        await self._select()

    async def on_list_view_selected(self, event: Any) -> None:
        await self._select()

    async def _select(self) -> None:
        lv = self.query_one("#search-list", ListView)
        idx = lv.index if lv.index is not None else 0
        if 0 <= idx < len(self._hits):
            self.dismiss(self._hits[idx])
        else:
            self.dismiss(-1)

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("down", "next_hit", "Next", show=False, priority=True),
        Binding("up", "prev_hit", "Prev", show=False, priority=True),
        Binding("tab", "cycle_scope", "范围", show=False, priority=True),
        Binding("enter", "choose", "Jump", show=False, priority=True),
    ]

    async def action_choose(self) -> None:
        await self._select()

    def action_close(self) -> None:
        self.dismiss(-1)

    def action_next_hit(self) -> None:
        self.query_one("#search-list", ListView).action_cursor_down()

    def action_prev_hit(self) -> None:
        self.query_one("#search-list", ListView).action_cursor_up()

    async def action_cycle_scope(self) -> None:
        idx = self.SCOPE_ORDER.index(self._scope)
        self._scope = self.SCOPE_ORDER[(idx + 1) % len(self.SCOPE_ORDER)]
        await self._populate(self.query_one("#search-input", Input).value or "")


# --------------------------------------------------------------------------
# Command palette: a modal with an Input + fuzzy list of slash commands
# --------------------------------------------------------------------------


class CommandPalette(ModalScreen[str]):
    """Type-ahead modal listing slash commands; Enter runs the selected one."""

    def __init__(self, entries: list[dict]) -> None:
        super().__init__()
        self.entries = entries or []
        self._matches: list[dict] = list(self.entries)

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            yield Static(self._title(), classes="modal-title")
            yield Input(placeholder="输入以过滤命令 / 动作 / 会话…", id="palette-input")
            self._lv = ListView(id="palette-list")
            yield self._lv
            yield Static("↑↓ 选择  " + glyph("sep") + "  Enter 执行  " + glyph("sep")
                         + "  Esc 关闭", id="palette-foot", classes="modal-foot")

    def _title(self) -> Text:
        pal = palette(self.app)
        t = Text()
        t.append(glyph("brand") + " ", style=f"bold {pal.accent}")
        t.append("命令面板", style=f"bold {pal.primary}")
        return t

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
        background: $background 60%;
    }
    #palette-box {
        width: 72;
        max-width: 92%;
        height: 70%;
        border: round $primary 55%;
        background: $panel;
        padding: 0 1 1 1;
    }
    #palette-box .modal-title {
        height: 1;
        text-style: bold;
    }
    #palette-box Input {
        height: 1;
        margin: 0 0 1 0;
        padding: 0 1;
        border: none;
        background: $panel-lighten-1;
    }
    #palette-list {
        height: 1fr;
        background: transparent;
        border: none;
    }
    #palette-list ListItem {
        padding: 0 1;
        background: transparent;
    }
    #palette-list ListItem.-highlight {
        background: $primary 45%;
    }
    #palette-box .modal-foot {
        height: 1;
        color: $text-muted;
    }
    """

    async def on_mount(self) -> None:
        await self._populate(self.entries)
        self.query_one("#palette-input", Input).focus()

    async def on_input_submitted(self, event: Any) -> None:
        """Enter in the filter box runs the highlighted/top entry.

        With no matches Enter must still close the palette — otherwise it looks
        frozen (the user pressed Enter and nothing happened).
        """
        lv = self.query_one("#palette-list", ListView)
        if not self._matches:
            self.dismiss({})
            return
        if lv.index is not None and 0 <= lv.index < len(self._matches):
            self.dismiss(self._matches[lv.index])
        else:
            self.dismiss(self._matches[0])

    async def _populate(self, entries: list[dict]) -> None:
        self._matches = entries
        lv = self.query_one("#palette-list", ListView)
        await lv.clear()
        try:
            foot = self.query_one("#palette-foot", Static)
            foot.update(f"{len(entries)} 项  " + glyph("sep") + "  ↑↓ 选择  "
                        + glyph("sep") + "  Enter 执行  " + glyph("sep") + "  Esc 关闭")
        except Exception:
            pass
        for e in entries[:40]:
            kind = _esc_markup(e.get("kind", ""))
            title = _esc_markup(e.get("title", ""))
            desc = _esc_markup(e.get("desc", ""))
            head = f"[dim]{kind:<4}[/dim] [b]{title}[/b]"
            label = Label(head if not desc else head + f"   [dim]{desc}[/dim]")
            await lv.append(ListItem(label))
        if entries:
            lv.index = 0

    async def on_input_changed(self, event: Any) -> None:
        q = (self.query_one("#palette-input", Input).value or "").strip().lower()
        if not q:
            matches = list(self.entries)
        else:
            matches = [e for e in self.entries
                       if q in str(e.get("title", "")).lower()
                       or q in str(e.get("desc", "")).lower()
                       or q in str(e.get("kind", "")).lower()]
        await self._populate(matches)

    async def on_list_view_selected(self, event: Any) -> None:
        lv = self.query_one("#palette-list", ListView)
        if not self._matches:
            self.dismiss({})
        elif lv.index is not None and 0 <= lv.index < len(self._matches):
            self.dismiss(self._matches[lv.index])

    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def action_close(self) -> None:
        self.dismiss({})


# --------------------------------------------------------------------------
# The application
# --------------------------------------------------------------------------


class UiuApp(App[None]):
    """Full-screen chat application wrapping the uiu agent engine."""

    TITLE = "uiu"
    SUB_TITLE = "your personal agent"

    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    #main-row {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_chat", "新会话", show=False, priority=True),
        Binding("ctrl+s", "toggle_sidebar", "侧栏", show=False, priority=True),
        Binding("ctrl+r", "history_search", "历史搜索", show=False, priority=True),
        Binding("ctrl+l", "clear_screen", "清屏", show=False, priority=True),
        Binding("ctrl+e", "command_palette", "命令面板", show=False, priority=True),
        Binding("ctrl+t", "theme_picker", "主题", show=False, priority=True),
        Binding("ctrl+x", "session_switcher", "会话切换", show=False, priority=True),
        Binding("ctrl+end", "scroll_bottom", "回到底部", show=False, priority=True),
        Binding("ctrl+y", "copy_last", "复制回答", show=False, priority=True),
        Binding("ctrl+z", "undo_delete", "撤销删除", show=False, priority=True),
        Binding("f3", "next_hit", "下一处命中", show=False, priority=True),
        Binding("shift+f3", "prev_hit", "上一处命中", show=False, priority=True),
        Binding("ctrl+u", "usage_panel", "用量", show=False, priority=True),
        Binding("ctrl+q", "quit_app", "退出", show=False, priority=True),
        Binding("f2", "toggle_statusbar", "状态条", show=False, priority=True),
        Binding("f1", "open_help", "帮助 (F1)", show=False, priority=True),
    ]

    def __init__(
        self,
        client: Any,
        ws: Workspace,
        *,
        model: str = "",
        cfg: Any = None,
        app_cfg: Any = None,
        turn_runner: Any = None,
        theme_name: str = DEFAULT_THEME,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.client = client
        self.ws = ws
        self.model = model
        self.cfg = cfg
        self.app_cfg = app_cfg
        self.theme_name = theme_name if theme_name in THEMES else DEFAULT_THEME
        self._agent_name = "agent"
        try:
            from ..config import resolve_agent_name
            self._agent_name = resolve_agent_name(app_cfg, ws)
        except Exception:
            pass
        self._messages: list[dict] = []
        self._tool_schemas: list[dict] = []
        self._cancel = None
        self._turn_running = False
        self._turn_count = 0
        self._bridge = ClarifyBridge(self.post_message)
        self._sessions = None
        self._turn_runner = turn_runner if turn_runner is not None else agent_turn
        self._worker = None
        self._tool_started: dict[str, float] = {}
        self._tool_args: dict[str, str] = {}
        self._tools_used = 0
        self._session_name = "default"
        self._pending_rows: dict[str, list[ToolRow]] = {}
        self._spin = 0
        self._sidebar_auto_hidden = False
        self._turn_started = 0.0
        self._uiu_custom_palette = None
        self._toast_until = 0.0
        self._search_bubbles: list[Any] = []
        self._search_idx = -1
        self._palette_recent: list[str] = []
        self._session_scroll: dict[str, float] = {}
        self._last_trash_id = ""      # Ctrl+Z 撤销上一次删除（会话/宏…）
        self._emit_alive = True     # 卸载后工作线程还会 emit，别往关闭的 loop 里丢协程

    # -- lifecycle -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        with Horizontal(id="main-row"):
            yield SideBar(id="sidebar")
            yield ChatView(self._agent_name, recent=self._recent_session(), id="chat")
        yield Composer(self._slash_words, agent_name=self._agent_name, id="composer")
        yield StatusBar(id="status")

    async def on_mount(self) -> None:
        register_themes(self)
        try:
            custom = palette_from_config(self.app_cfg)
        except Exception:
            custom = None
        if custom is not None:
            try:
                self.register_theme(custom.to_theme())
                self._uiu_custom_palette = custom
                self.theme_name = custom.name
            except Exception:
                pass
        try:
            self.theme = self.theme_name
        except Exception:
            pass

        # agent name / config into header + status
        hdr = self.query_one("#header", HeaderBar)
        hdr.agent = self._agent_name
        hdr.model = self._model_display()
        hdr.ws = str(self.ws.root)
        try:
            hdr.version = _VERSION
        except Exception:
            pass
        try:
            n_tools = len(_tools.tool_defs())
            n_skills = len(self.ws.skills)
        except Exception:
            n_tools, n_skills = 0, 0
        hdr.tools_n = n_tools
        hdr.skills_n = n_skills
        hdr.session = self._session_name

        st = self.query_one("#status", StatusBar)
        st.agent = self._agent_name
        st.model = self._model_display()
        st.tools_n = n_tools
        st.skills_n = n_skills
        st.session = self._session_name
        self.set_interval(0.25, self._tick)

        chat = self.query_one("#chat", ChatView)
        chat.version = _VERSION
        chat.tools_n = n_tools
        chat.skills_n = n_skills
        try:
            from .widgets import WelcomeBanner
            await chat.query_one("#empty-hint", WelcomeBanner).set_context(
                version=_VERSION, tools_n=n_tools, skills_n=n_skills)
        except Exception:
            pass

        # tool schemas: builtins + skills
        self._tool_schemas = self._rebuild_schemas()

        # message history: auto-resume the last session if any
        prev = None
        try:
            from .. import sessions as _sessions
            self._sessions = _sessions
            prev = _sessions.load_session(self.ws.root, self._session_name)
            if prev and len(prev) > 1:
                self._messages = prev
        except Exception:
            pass
        if not self._messages:
            self._messages = [{"role": "system", "content": self.ws.system_prompt()}]

        # host context injection (delegation + clarify)
        try:
            from ..delegation import set_context
            set_context(self.client, self.cfg, self.ws, self._tool_schemas)
        except Exception:
            pass
        try:
            from ..clarify import set_ask_handler
            set_ask_handler(self._bridge.ask_sync)
        except Exception:
            pass
        # sensitive-tool hard confirmation (send_wechat / shutdown / macro_play)
        try:
            from ..confirm import set_confirm_handler

            def _host_confirm(name: str, preview: str) -> str:
                ans = self._bridge.ask_sync(
                    f"确认执行 {name}？\n\n参数: {preview}\n\n输入 yes 确认，no 取消",
                    ["yes", "no"],
                )
                return ans if ans in ("yes", "y", "ok", "1") else "no"

            set_confirm_handler(_host_confirm)
        except Exception:
            pass
        # memory hot-reload hook
        try:
            from ..learning import register_memory_hook
            register_memory_hook(self.ws.reload_memory)
        except Exception:
            pass

        # TUI 侧也接上日志：出现问题时 workspace/logs/uiu.log 里要有线索
        try:
            from ..log import get_logger, setup_logging
            setup_logging(self.ws.root)
            get_logger("tui").info("TUI 启动（agent=%s, model=%s）", self._agent_name, self._model_display())
        except Exception:
            pass

        self._refresh_ctx()
        self._refresh_recent()
        self._sync_title()
        # sidebar collapsed by default (ctrl+s to open)
        try:
            self.query_one("#sidebar").display = False
        except Exception:
            pass
        # seed ↑/↓ recall with this session's prompts
        try:
            composer = self.query_one("#composer", Composer)
            composer.set_history([str(m.get("content", "")) for m in self._messages
                                  if m.get("role") == "user"])
        except Exception:
            pass
        if prev and len(prev) > 1:
            await chat.load_transcript(self._messages)
            await chat.add_notice(
                f"已恢复会话 {self._session_name}（" + glyph("arrow")
                + " Ctrl+X 切换 · /new 开新会话）")

    def on_resize(self, event: Any) -> None:
        """窄终端自动收起侧栏，变宽时还原（用户手动开合优先）。"""
        try:
            sb = self.query_one("#sidebar", SideBar)
        except Exception:
            return
        narrow = getattr(event, "size", None) is not None and event.size.width < 88
        if narrow:
            if sb.display:
                self._sidebar_auto_hidden = True
                sb.display = False
        elif self._sidebar_auto_hidden:
            sb.display = True
            self._sidebar_auto_hidden = False

    def _tick(self) -> None:
        """Animate the status spinner and any in-flight tool rows."""
        self._spin += 1
        try:
            st = self.query_one("#status", StatusBar)
            st.tick()
            if self._turn_running and self._turn_started:
                st.elapsed = f"{time.monotonic() - self._turn_started:.0f}s"
            try:
                unread = self.query_one("#chat", ChatView).unread()
            except Exception:
                unread = False
            st.notice = "↓ 新内容 · Ctrl+End" if unread else ""
            if st.toast and self._toast_until and time.monotonic() > self._toast_until:
                st.toast = ""
                self._toast_until = 0.0
        except Exception:
            pass
        try:
            for row in self.query_one("#chat", ChatView).running_tool_rows():
                row.tick(self._spin)
        except Exception:
            pass

    def _recent_session(self) -> dict[str, Any]:
        """Most recent *other* saved session, for the empty-state resume card."""
        try:
            from .. import sessions as _sessions
            items = _sessions.list_sessions(self.ws.root)
        except Exception:
            return {}
        candidates = [i for i in items
                      if str(i.get("id") or "") and str(i.get("id")) != self._session_name]
        named = [i for i in candidates if not str(i.get("id")).startswith("auto-")]
        for item in (named or candidates):
            sid = str(item.get("id") or "")
            teaser = ""
            try:
                msgs = _sessions.load_session(self.ws.root, sid) or []
                for m in reversed(msgs):
                    if m.get("role") == "user" and str(m.get("content") or "").strip():
                        teaser = " ".join(str(m["content"]).split())[:56]
                        break
            except Exception:
                pass
            return {"id": sid, "turns": item.get("turns", 0),
                    "updated": item.get("updated", 0), "teaser": teaser}
        return {}

    async def on_chat_view_resume_picked(self, event: ChatView.ResumePicked) -> None:
        event.stop()
        if self._chat() is None:
            return
        await self._on_session_picked(event.session_id)

    async def on_chat_view_copy_requested(self, event: ChatView.CopyRequested) -> None:
        event.stop()
        if self._chat() is None:
            return
        await self._copy(event.text, "这条回答")

    async def on_chat_view_expand_requested(self, event: ChatView.ExpandRequested) -> None:
        """User clicked the folded-history bar: re-render a deeper window."""
        event.stop()
        chat = self._chat()
        if chat is None:
            return
        if chat._folded <= 0 or chat.window >= ChatView.MAX_RENDER:
            chat._suspend_top_load = False
            chat._user_scrolled_up = False
            return
        old_window = chat.window
        target = min(ChatView.MAX_RENDER, old_window + ChatView.PAGE)
        if target <= old_window:
            chat._suspend_top_load = False
            chat._user_scrolled_up = False
            return
        # 记住视口顶部那一行，展开后把它钉回原位（否则会被顶走）
        anchor = chat.top_visible_index()
        await chat.load_transcript(self._messages, cap=target, stick=False)
        # 布局完成后再锚定（中途不能放开自动加载，否则会被反复触发）
        chat.anchor_to_index_later(anchor + (target - old_window))

    def _toast(self, text: str, *, kind: str = "info", seconds: float = 3.0) -> None:
        """Transient status-bar feedback (does not pollute the transcript)."""
        try:
            st = self.query_one("#status", StatusBar)
        except Exception:
            return
        st.toast = text
        st.toast_kind = kind
        self._toast_until = time.monotonic() + max(1.0, seconds)

    def _sync_title(self) -> None:
        """Reflect the session in the terminal window/tab title."""
        try:
            self.title = "uiu"
            self.sub_title = f"{self._session_name} · {self._model_display()}"
        except Exception:
            pass

    def _chat(self) -> Any:
        """The message area, or None when we are already unmounted.

        Queued messages (fold expansion, copy, resume) can be delivered during
        teardown — handlers must bail out instead of raising NoMatches.
        """
        try:
            return self.query_one("#chat", ChatView)
        except Exception:
            return None

    def _model_display(self) -> str:
        if isinstance(self.model, str) and self.model:
            return self.model
        try:
            return getattr(self.cfg, "default", "-")
        except Exception:
            return "-"

    def _rebuild_schemas(self) -> list[dict]:
        schemas = _tools.tool_defs()
        for s in self.ws.skills:
            schemas.append(s.to_tool_def())
        return schemas

    def _slash_words(self, prefix: str = "") -> list[str]:
        """Words offered by the composer completion / command palette."""
        words: list[str] = []
        try:
            from ..slash import REGISTRY
            for name in REGISTRY:
                words.append(f"/{name}")
        except Exception:
            pass
        if prefix.startswith("/") and " " not in prefix:
            return [w for w in words if w.startswith(prefix)]
        return words

    def _context_chars(self) -> int:
        try:
            from ..sessions import context_chars
            return context_chars(self._messages)
        except Exception:
            return 0

    def _refresh_ctx(self) -> None:
        try:
            st = self.query_one("#status", StatusBar)
        except Exception:
            return
        turns = sum(1 for m in self._messages if m.get("role") == "user")
        st.turns = turns
        st.session = self._session_name
        chars = self._context_chars()
        st.set_ctx(chars)
        try:
            from ..sessions import estimate_tokens
            st.tokens = estimate_tokens(chars)
        except Exception:
            st.tokens = 0
        self._refresh_sidebar(turns, st.ctx_pct)

    def _refresh_recent(self) -> None:
        """Refresh the sidebar's recent-session list (cheap: no JSON parsing)."""
        try:
            sb = self.query_one("#sidebar", SideBar)
        except Exception:
            return
        try:
            from .. import sessions as _sessions
            items = _sessions.recent_sessions(self.ws.root, 8)
        except Exception:
            items = []
        try:
            self.run_worker(sb.update_recent(items, self._session_name),
                            exclusive=False)
        except Exception:
            pass

    def _refresh_sidebar(self, turns: int, ctx_pct: int) -> None:
        try:
            sb = self.query_one("#sidebar", SideBar)
        except Exception:
            return
        try:
            self.run_worker(
                sb.update_stats(turns=turns, tools=self._tools_used, ctx_pct=ctx_pct,
                                session=self._session_name),
                exclusive=False,
            )
        except Exception:
            pass

    # -- event handlers from the worker ----------------------------------

    async def on_thought_chunk(self, event: ThoughtChunk) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.stream_thought(event.delta)

    async def on_text_chunk(self, event: TextChunk) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.stream(event.delta)

    async def on_tool_call_event(self, event: ToolCallEvent) -> None:
        chat = self.query_one("#chat", ChatView)
        self._tool_started[event.name] = time.monotonic()
        try:
            args = json.dumps(event.arguments, ensure_ascii=False)
        except Exception:
            args = ""
        self._tool_args[event.name] = args
        preview = args if len(args) <= 80 else args[:79] + "…"
        try:
            row = await chat.add_tool_call(event.name, preview)
            self._pending_rows.setdefault(event.name, []).append(row)
        except Exception:
            pass
        try:
            self.query_one("#composer", Composer).set_activity(event.name)
        except Exception:
            pass

    async def on_tool_result_event(self, event: ToolResultEvent) -> None:
        chat = self.query_one("#chat", ChatView)
        ok = not (event.result or "").startswith("[error]")
        self._tools_used += 1
        one = " ".join((event.result or "").split())
        preview = one[:100] + ("…" if len(one) > 100 else "")
        started = self._tool_started.pop(event.name, None)
        seconds = (time.monotonic() - started) if started else None
        args = self._tool_args.pop(event.name, "")
        pending = self._pending_rows.get(event.name) or []
        if pending:
            row = pending.pop(0)
            if not pending:
                self._pending_rows.pop(event.name, None)
            try:
                row.set_result(ok, preview, detail=event.result or "", seconds=seconds)
            except Exception:
                pass
        else:
            await chat.add_tool(
                event.name, ok, preview,
                detail=event.result or "",
                seconds=seconds,
                args=args,
            )
        try:
            if not self._pending_rows:
                self.query_one("#composer", Composer).set_activity("")
        except Exception:
            pass
        self._refresh_ctx()

    async def on_notice_event(self, event: NoticeEvent) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.add_notice(event.text)

    async def on_turn_done(self, event: TurnDone) -> None:
        self._turn_running = False
        self._turn_count += 1
        chat = self.query_one("#chat", ChatView)
        await chat.finish_assistant()
        composer = self.query_one("#composer", Composer)
        composer.set_busy(False)
        composer.clear()
        composer.focus_input()
        st = self.query_one("#status", StatusBar)
        st.mode = "idle"
        st.elapsed = ""
        self._turn_started = 0.0
        self._autosave()
        if getattr(event, "elapsed", 0):
            await chat.add_notice(f"完成，用时 {event.elapsed:.1f}s")
        self._refresh_ctx()

    async def on_turn_error(self, event: TurnError) -> None:
        self._turn_running = False
        chat = self.query_one("#chat", ChatView)
        await chat.finish_assistant()
        composer = self.query_one("#composer", Composer)
        composer.set_busy(False)
        composer.focus_input()
        st = self.query_one("#status", StatusBar)
        st.mode = "error"
        st.elapsed = ""
        self._turn_started = 0.0
        err = event.error
        hint = ""
        msg = str(err)
        tn = type(err).__name__
        if "401" in msg or "invalid_api_key" in msg.lower() or "AuthenticationError" in tn:
            hint = "\n\n→ API key 无效：运行 uiu config --api-key <key>，或 uiu model 重新选模型"
        elif "context_length" in msg.lower() or "maximum context" in msg.lower():
            hint = "\n\n→ 对话太长：输入 /clear 清空后重试"
        await chat.add_error(f"[error] {tn}: {msg[:300]}{hint}")
        self._autosave()

    async def on_interrupted(self, event: Interrupted) -> None:
        self._turn_running = False
        chat = self.query_one("#chat", ChatView)
        await chat.finish_assistant()
        await chat.add_notice("（已中断）")
        composer = self.query_one("#composer", Composer)
        composer.set_busy(False)
        composer.clear()
        composer.focus_input()
        st = self.query_one("#status", StatusBar)
        st.mode = "idle"
        st.elapsed = ""
        self._turn_started = 0.0
        self._autosave()

    async def on_ask_user(self, event: AskUser) -> None:
        """Clarify bridge: show modal, hand answer back to the waiting thread."""
        def _on_done(res):
            self._bridge.answer(res if res is not None else "")
        self.push_screen(ConfirmModal(event.question, event.options), callback=_on_done)

    # -- sending a user turn --------------------------------------------

    async def _send(self, text: str) -> None:
        if self._turn_running:
            # 静默丢弃会让人以为按键坏了
            self._toast("agent 正在回复，等这轮结束再发", kind="error")
            return
        chat = self._chat()
        if chat is None:
            return
        if text.startswith("/") and not text.startswith("//"):
            handled, quit_sig = await self._dispatch_slash(text)
            if quit_sig == "__quit__":
                self.exit()
                return
            if handled:
                self._autosave()
                self._refresh_ctx()
                return
        await chat.add_user(text)
        self._messages.append({"role": "user", "content": text})
        # 回答气泡不再预建：交给第一个 text chunk，好让推理块排在回答之前

        composer = self.query_one("#composer", Composer)
        composer.set_busy(True)
        st = self.query_one("#status", StatusBar)
        st.mode = "running"
        st.elapsed = ""
        self._turn_started = time.monotonic()

        import threading
        self._cancel = threading.Event()
        cancel_ev = self._cancel

        def emit(msg: Any) -> None:
            if not self._emit_alive:
                return
            try:
                self.call_from_thread(self.post_message, msg)
            except Exception:
                pass

        self._turn_running = True
        import threading as _th
        worker = _th.Thread(
            target=self._turn_runner,
            kwargs={
                "client": self.client,
                "messages": self._messages,
                "tool_schemas": self._tool_schemas,
                "skills": self.ws.skills,
                "model": self.model,
                "cfg": self.cfg,
                "emit": emit,
                "cancel": cancel_ev,
            },
            name="agent-turn",
            daemon=True,
        )
        worker.start()
        self._worker = worker

    async def _run_blocking_slash(self, dispatch, text: str, sctx, head: str):
        """Run a slash command off the UI thread so slow ones can't freeze it."""
        import asyncio as _asyncio
        composer = None
        st = None
        try:
            composer = self.query_one("#composer", Composer)
            st = self.query_one("#status", StatusBar)
            composer.set_busy(True, cancellable=False)
            composer.set_activity(f"{head} 执行中")
            st.mode = "running"
            st.elapsed = ""
            self._turn_started = time.monotonic()
        except Exception:
            composer = None
        try:
            return await _asyncio.to_thread(dispatch, text, sctx)
        finally:
            self._turn_started = 0.0
            try:
                if composer is not None:
                    composer.set_busy(False)
                if st is not None:
                    st.mode = "idle"
                    st.elapsed = ""
            except Exception:
                pass

    async def _dispatch_slash(self, text: str):
        # TUI-native commands render as overlays instead of inline text
        head = text.strip().split()[0] if text.strip() else ""
        if head == "/theme":
            await self.action_theme_picker()
            return True, None
        if head == "/usage":
            await self.action_usage_panel()
            return True, None
        if head == "/status":
            await self.action_status_panel()
            return True, None
        if head == "/search":
            arg = text.strip().split(None, 1)
            q = arg[1].strip() if len(arg) > 1 else ""
            self.push_screen(SessionSearchModal(self.ws.root, q),
                             callback=self._on_search_pick)
            return True, None
        if head == "/export":
            arg = text.strip().split(None, 1)
            name = arg[1].strip() if len(arg) > 1 else ""
            await self._export_transcript(name)
            return True, None
        if head == "/copy":
            arg = text.strip().split(None, 1)
            if len(arg) > 1 and arg[1].strip().lower() in ("all", "全部"):
                await self._copy(self._transcript_markdown(), "整个会话")
            else:
                await self.action_copy_last()
            return True, None
        if head == "/sessions" and len(text.strip().split()) == 1:
            await self.action_session_switcher()
            return True, None
        from ..slash import SlashContext, dispatch
        say_out: list[str] = []
        sctx = SlashContext(
            ws=self.ws,
            cfg=self.app_cfg if self.app_cfg is not None else self.cfg,
            client=self.client,
            model=self.model,
            messages=self._messages,
            say=say_out.append,
            tool_schemas=self._tool_schemas,
        )
        # 有些命令是慢活（/compact 要走 LLM、/cron run 要跑任务）——放到工作线程，
        # 否则会卡死整个界面；期间用状态条提示正在执行什么。
        handled, quit_sig = await self._run_blocking_slash(dispatch, text, sctx, head)
        self.ws = sctx.ws
        self._tool_schemas = self._rebuild_schemas()
        chat = self.query_one("#chat", ChatView)
        out_text = "\n".join(line.rstrip() for line in say_out if line.strip())
        if out_text:
            await chat.add_output(out_text, head)
        return handled, quit_sig

    # -- composer messages ----------------------------------------------

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        event.stop()
        composer = self.query_one("#composer", Composer)
        composer.clear()
        await self._send(event.text)

    async def on_composer_cancelled(self, event: Composer.Cancelled) -> None:
        event.stop()
        if self._cancel is not None and self._turn_running:
            self._cancel.set()
            chat = self.query_one("#chat", ChatView)
            await chat.add_notice("（中断请求已发送…）")

    async def on_chat_view_suggestion_picked(self, event: ChatView.SuggestionPicked) -> None:
        event.stop()
        composer = self.query_one("#composer", Composer)
        composer.clear()
        await self._send(event.text)

    async def on_side_bar_command_picked(self, event: SideBar.CommandPicked) -> None:
        event.stop()
        cmd = event.command
        if cmd.startswith("__action__:"):
            await self._run_action(cmd.split(":", 1)[1])
            return
        if cmd.startswith("__session__:"):
            await self._on_session_picked(cmd.split(":", 1)[1])
            return
        await self._send(cmd)

    async def _run_action(self, name: str) -> None:
        if name == "palette":
            await self.action_command_palette()
        elif name == "theme":
            await self.action_theme_picker()
        elif name == "help":
            await self.action_open_help()
        elif name == "sessions":
            await self.action_session_switcher()
        elif name == "find":
            await self.action_history_search()
        elif name == "bottom":
            await self.action_scroll_bottom()
        elif name == "sidebar":
            await self.action_toggle_sidebar()
        elif name == "usage":
            await self.action_usage_panel()
        elif name == "status":
            await self.action_status_panel()

    # -- session & autosave ----------------------------------------------

    def _autosave(self) -> None:
        if self._sessions is None:
            return
        try:
            self._sessions.save_session(self.ws.root, self._session_name, self._messages)
        except Exception:
            pass

    # -- actions ----------------------------------------------------------

    async def action_new_chat(self) -> None:
        if self._turn_running:
            self._toast("agent 正在回复，等这轮结束再开新会话", kind="error")
            return
        # snapshot the old conversation, then start a clean session
        if self._sessions is not None and len(self._messages) > 1:
            try:
                snap = "auto-" + time.strftime("%m%d-%H%M%S")
                self._sessions.save_session(self.ws.root, snap, self._messages)
            except Exception:
                pass
        self._messages = [{"role": "system", "content": self.ws.system_prompt()}]
        self._session_name = "default"
        self._tools_used = 0
        self._pending_rows.clear()
        self._search_bubbles = []
        self._search_idx = -1
        chat = self.query_one("#chat", ChatView)
        await chat.clear_chat()
        hdr = self.query_one("#header", HeaderBar)
        hdr.session = self._session_name
        st = self.query_one("#status", StatusBar)
        st.session = self._session_name
        st.mode = "idle"
        self._refresh_ctx()
        self._refresh_recent()
        self._sync_title()
        composer = self.query_one("#composer", Composer)
        composer.clear()
        composer.focus_input()

    async def action_toggle_sidebar(self) -> None:
        sb = self.query_one("#sidebar", SideBar)
        sb.display = not sb.display
        self._sidebar_auto_hidden = False

    async def action_history_search(self) -> None:
        """Ctrl+R: search the transcript and jump to a hit."""
        chat = self.query_one("#chat", ChatView)
        bubbles = chat.message_bubbles()
        if not bubbles:
            await chat.add_notice("（当前会话还没有可搜索的消息）")
            return
        entries = []
        for b in bubbles:
            kind = "对话"
            if isinstance(b, OutputRow):
                who = f"{glyph('prompt')} {b.command}"
                kind = "输出"
            elif b.role == "user":
                who = "你"
            elif b.role == "assistant":
                who = self._agent_name
            else:
                who = "错误"
            entries.append({"who": who, "time": getattr(b, "stamp", ""),
                            "kind": kind, "text": b.get_text()})

        def _on_picked(idx):
            if idx is None or idx < 0 or idx >= len(bubbles):
                return
            # 记住命中列表，之后可以用 F3 / Shift+F3 逐条跳
            self._search_bubbles = bubbles
            self._search_idx = idx
            chat.scroll_to_bubble(bubbles[idx])
            self._toast(f"命中 {idx + 1}/{len(bubbles)}  {glyph('sep')}  F3 下一处")

        self.push_screen(SearchModal(entries), callback=_on_picked)

    async def action_clear_screen(self) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.clear_chat()
        await chat.add_notice("（已清屏 — 对话上下文保留；/clear 清空上下文）")

    def _palette_entries(self) -> list[dict]:
        """Everything the palette can do: slash 命令 / 动作 / 最近会话。"""
        entries: list[dict] = []
        # 动作与最近会话放前面：这是面板最常用的部分，slash 命令按字典序排后面
        for title, desc, run in (
            ("新会话", "Ctrl+N", "/new"),
            ("切换会话", "Ctrl+X · 已存会话列表", "__action__:sessions"),
            ("切换主题", "Ctrl+T · 4 套配色 + 自定义", "__action__:theme"),
            ("搜索当前对话", "Ctrl+R · F3 逐个跳命中", "__action__:find"),
            ("跨会话检索", "/search <关键词>", "/search"),
            ("会话用量", "Ctrl+U · 上下文 / token", "/usage"),
            ("运行状态", "模型 / key / 渠道 / MCP", "/status"),
            ("复制上一条回答", "Ctrl+Y", "/copy"),
            ("导出整段会话", "/copy all · Markdown", "/copy all"),
            ("导出到文件", "/export [名字] · workspace/exports/", "/export"),
            ("保存会话", "/save [名字]", "/save"),
            ("压缩旧对话", "/compact", "/compact"),
            ("查看技能", "/skills", "/skills"),
            ("定时任务", "/cron list", "/cron list"),
            ("自动化建议", "/suggestions", "/suggestions"),
            ("回到底部", "Ctrl+End", "__action__:bottom"),
            ("开合侧栏", "Ctrl+S", "__action__:sidebar"),
            ("帮助", "F1", "__action__:help"),
        ):
            entries.append({"kind": "动作", "title": title, "desc": desc, "run": run})
        try:
            from .. import sessions as _sessions
            for s in _sessions.recent_sessions(self.ws.root, 6):
                sid = str(s.get("id"))
                if not sid or sid == self._session_name:
                    continue
                entries.append({"kind": "会话", "title": sid,
                                "desc": "打开这个会话",
                                "run": "__session__:" + sid})
        except Exception:
            pass
        try:
            from ..slash import REGISTRY
            for name in sorted(REGISTRY):
                entries.append({
                    "kind": "命令", "title": f"/{name}",
                    "desc": str(REGISTRY[name].get("description", "")),
                    "run": f"/{name}",
                })
        except Exception:
            pass
        # 最近用过的排前面（本次会话内记忆），其余保持自然顺序
        def _rank(e: dict) -> tuple[int, int]:
            run = str(e.get("run") or "")
            try:
                return (0, self._palette_recent.index(run))
            except ValueError:
                return (1, 0)
        entries.sort(key=_rank)
        return entries

    def _remember_palette(self, run: str) -> None:
        if not run:
            return
        try:
            self._palette_recent.remove(run)
        except ValueError:
            pass
        self._palette_recent.insert(0, run)
        del self._palette_recent[8:]

    async def _run_palette_entry(self, entry: dict) -> None:
        self._remember_palette(str((entry or {}).get("run") or ""))
        run = str((entry or {}).get("run") or "")
        if not run:
            return
        if run.startswith("__action__:"):
            await self._run_action(run.split(":", 1)[1])
        elif run.startswith("__session__:"):
            await self._on_session_picked(run.split(":", 1)[1])
        else:
            await self._send(run)

    async def action_command_palette(self) -> None:
        entries = self._palette_entries()
        if not entries:
            return

        def _on_picked(entry):
            if entry:
                try:
                    self.run_worker(self._run_palette_entry(entry), exclusive=False)
                except Exception:
                    pass
        self.push_screen(CommandPalette(entries), callback=_on_picked)

    def _apply_custom_colors(self, base_name: str) -> bool:
        """Re-derive the custom palette (tui.colors) on top of *base_name*."""
        cfg = self.app_cfg
        if cfg is None:
            return False
        try:
            tui = dict(getattr(cfg, "tui", {}) or {})
            tui["theme"] = base_name
            cfg.tui = tui
            custom = palette_from_config(cfg)
        except Exception:
            custom = None
        if custom is None:
            self._uiu_custom_palette = None
            return False
        try:
            self.register_theme(custom.to_theme())
        except Exception:
            return False
        self._uiu_custom_palette = custom
        return True

    def _custom_note(self) -> str:
        if self._uiu_custom_palette is None:
            return ""
        try:
            colors = dict((getattr(self.app_cfg, "tui", {}) or {}).get("colors") or {})
        except Exception:
            colors = {}
        if not colors:
            return ""
        preview = "  ".join(f"{k} {v}" for k, v in list(colors.items())[:3])
        more = f" 等 {len(colors)} 处" if len(colors) > 3 else ""
        return "tui.colors 覆盖中：" + preview + more

    async def action_theme_picker(self) -> None:
        previous = self.theme

        def _on_picked(result):
            if not result:
                try:
                    self.theme = previous
                except Exception:
                    pass
                return
            try:
                self.theme = result
                self.theme_name = result
                self._persist_theme(result)
                # tui.colors 覆盖在所选主题之上，切主题后重新派生
                if self._apply_custom_colors(result):
                    self.theme = self._uiu_custom_palette.name
                self._toast(glyph("ok") + f" 主题已切换：{result}")
            except Exception:
                pass

        self.push_screen(ThemePicker(previous or DEFAULT_THEME, self._custom_note()),
                         callback=_on_picked)

    def _persist_theme(self, name: str) -> None:
        """Remember the chosen theme in workspace/config.yaml."""
        try:
            from ..config import load_config, save_config
            cfg = load_config(self.ws.root)
            prefs = dict(getattr(cfg, "tui", {}) or {})
            prefs["theme"] = name
            cfg.tui = prefs
            save_config(self.ws.root, cfg)
            if self.app_cfg is not None:
                try:
                    self.app_cfg.tui = prefs
                except Exception:
                    pass
        except Exception:
            pass

    def _usage_stats(self) -> dict[str, Any]:
        try:
            from .. import sessions as _sessions
            chars = _sessions.context_chars(self._messages)
            tokens = _sessions.estimate_tokens(chars)
            saved = len(_sessions.list_sessions(self.ws.root))
        except Exception:
            chars, tokens, saved = 0, 0, 0
        try:
            n_tools = len(_tools.tool_defs())
            n_skills = len(self.ws.skills)
        except Exception:
            n_tools, n_skills = 0, 0
        users = sum(1 for m in self._messages if m.get("role") == "user")
        assts = sum(1 for m in self._messages if m.get("role") == "assistant")
        return {
            "model": self._model_display(),
            "agent": self._agent_name,
            "session": self._session_name,
            "turns": users,
            "pct": min(99, int(chars / 1200)),
            "chars": chars,
            "tokens": tokens,
            "user_msgs": users,
            "asst_msgs": assts,
            "tools": n_tools,
            "skills": n_skills,
            "saved": saved,
            "workspace": str(self.ws.root),
        }

    def _status_stats(self) -> dict[str, Any]:
        cfgm = self.cfg
        app_cfg = self.app_cfg
        usage = self._usage_stats()
        try:
            api_key = cfgm.resolved_api_key() if cfgm is not None else ""
        except Exception:
            api_key = ""
        chans = list(getattr(app_cfg, "channels", []) or [])
        enabled = sum(1 for c in chans if getattr(c, "enabled", False))
        return {
            "agent": self._agent_name,
            "model": self._model_display(),
            "base_url": getattr(cfgm, "base_url", ""),
            "api_mode": getattr(cfgm, "api_mode", ""),
            "api_key": bool(api_key),
            "api_key_env": getattr(cfgm, "api_key_env", ""),
            "channels": f"{enabled} 启用 / {len(chans)} 配置",
            "mcp": len(getattr(app_cfg, "mcp_servers", []) or []),
            "tools": usage.get("tools", 0),
            "skills": usage.get("skills", 0),
            "session": self._session_name,
            "turns": usage.get("turns", 0),
            "saved": usage.get("saved", 0),
            "theme": self.theme,
            "version": _VERSION,
            "workspace": str(self.ws.root),
        }

    async def action_status_panel(self) -> None:
        await self.push_screen(StatusModal(self._status_stats()))

    # -- 复制 ------------------------------------------------------------

    def _last_answer(self) -> str:
        try:
            bubbles = self.query_one("#chat", ChatView).message_bubbles()
        except Exception:
            return ""
        for b in reversed(bubbles):
            if b.role == "assistant" and (b.get_text() or "").strip():
                return b.get_text()
        return ""

    def _turns(self) -> list[dict]:
        return [m for m in self._messages
                if m.get("role") in ("user", "assistant")
                and str(m.get("content") or "").strip()]

    def _transcript_markdown(self) -> str:
        if not self._turns():
            return ""
        lines = [f"# uiu 会话记录 · {self._session_name}", ""]
        turns = sum(1 for m in self._messages if m.get("role") == "user")
        lines.append(f"（{turns} 轮 · {time.strftime('%Y-%m-%d %H:%M')}）")
        lines.append("")
        for m in self._messages:
            role = m.get("role")
            content = str(m.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                lines += ["## 你", "", content, ""]
            elif role == "assistant":
                lines += [f"## {self._agent_name}", "", content, ""]
        return "\n".join(lines).rstrip() + "\n"

    async def _copy(self, text: str, what: str) -> None:
        if not text.strip():
            self._toast(f"没有可复制的{what}", kind="error")
            return
        try:
            from .clipboard import copy_text
            ok, detail = copy_text(text)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        if ok:
            self._toast(glyph("ok") + f" 已复制{what} · {len(text)} 字")
        else:
            self._toast(f"复制失败：{detail}", kind="error", seconds=6.0)

    async def action_copy_last(self) -> None:
        await self._copy(self._last_answer(), "上一条回答")

    async def _export_transcript(self, name: str = "") -> None:
        """Write the conversation to workspace/exports/<name>.md."""
        chat = self.query_one("#chat", ChatView)
        if not self._turns():
            self._toast("会话还是空的，没什么可导出", kind="error")
            return
        text = self._transcript_markdown()
        safe = "".join(c for c in (name or self._session_name)
                       if c.isalnum() or c in "-_")[:40] or "session"
        try:
            out_dir = self.ws.root / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{safe}.md"
            path.write_text(text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._toast(f"导出失败：{exc}", kind="error", seconds=6.0)
            return
        self._toast(glyph("ok") + f" 已导出 {len(text)} 字 → exports/{safe}.md",
                    seconds=5.0)
        await chat.add_notice(f"已导出会话到 {path}")

    # -- 跨会话检索 ------------------------------------------------------

    def _on_search_pick(self, hit: Any) -> None:
        if not hit:
            return
        try:
            self.run_worker(self._open_search_hit(hit), exclusive=False)
        except Exception:
            pass

    async def _open_search_hit(self, hit: dict) -> None:
        sid = str(hit.get("session") or "")
        if sid and sid != self._session_name:
            await self._on_session_picked(sid)
        chat = self.query_one("#chat", ChatView)
        snippet = " ".join(str(hit.get("text") or "").split())
        frag = snippet[:14]
        for b in chat.message_bubbles():
            if frag and frag in (b.get_text() or ""):
                chat.scroll_to_bubble(b)
                return
        if snippet:
            await chat.add_notice(
                f"命中（{sid} · {hit.get('role')}）：{snippet[:120]}")

    async def _cycle_hit(self, delta: int) -> None:
        hits = self._search_bubbles
        if not hits:
            self._toast("先用 Ctrl+R 搜索当前对话", kind="error")
            return
        self._search_idx = (self._search_idx + delta) % len(hits)
        try:
            chat = self.query_one("#chat", ChatView)
            chat.scroll_to_bubble(hits[self._search_idx])
        except Exception:
            return
        self._toast(f"命中 {self._search_idx + 1}/{len(hits)}  "
                    + glyph("sep") + "  F3 下一处 · Shift+F3 上一处")

    async def action_next_hit(self) -> None:
        await self._cycle_hit(1)

    async def action_prev_hit(self) -> None:
        await self._cycle_hit(-1)

    async def action_undo_delete(self) -> None:
        """撤销上一次删除：把回收站里最近一条还原回来（审计 §4.1）。"""
        if not self._last_trash_id:
            self._toast("没有可撤销的删除", kind="error")
            return
        try:
            from ..trash import restore
            ok, msg = restore(self.ws.root, self._last_trash_id)
        except Exception as exc:
            ok, msg = False, f"撤销失败: {type(exc).__name__}: {exc}"
        if ok:
            self._last_trash_id = ""
            self._toast(glyph("ok") + " " + msg)
            await self._refresh_after_undo()
        else:
            self._toast(msg, kind="error")

    async def _refresh_after_undo(self) -> None:
        try:
            self._refresh_recent()
            self._refresh_ctx()
        except Exception:
            pass

    async def action_scroll_bottom(self) -> None:
        try:
            await self.query_one("#chat", ChatView).scroll_to_bottom()
        except Exception:
            pass

    async def action_usage_panel(self) -> None:
        await self.push_screen(UsageModal(self._usage_stats()))

    async def action_session_switcher(self) -> None:
        self.push_screen(SessionSwitcher(self.ws.root, self._session_name),
                         callback=self._on_session_picked)

    async def _on_session_picked(self, sid: Any) -> None:
        if not sid or sid == self._session_name:
            return
        if self._turn_running:
            self._toast("agent 正在回复，等这轮结束再切会话", kind="error")
            return
        self._autosave()
        try:
            from .. import sessions as _sessions
            msgs = _sessions.load_session(self.ws.root, str(sid))
        except Exception:
            msgs = None
        if not msgs:
            return
        # 记住离开的那个会话滚到哪儿了
        try:
            chat_now = self.query_one("#chat", ChatView)
            self._session_scroll[self._session_name] = chat_now.scroll_offset_y()
        except Exception:
            pass
        self._session_name = str(sid)
        # 旧的高亮/命中列表指向即将被销毁的气泡，必须一起清掉
        self._search_bubbles = []
        self._search_idx = -1
        base = [{"role": "system", "content": self.ws.system_prompt()}]
        restored = [m for m in msgs if m.get("role") != "system"] or []
        self._messages = base + restored
        self._tools_used = 0
        self._pending_rows.clear()
        chat = self.query_one("#chat", ChatView)
        saved = self._session_scroll.get(self._session_name) or 0.0
        rendered = await chat.load_transcript(restored, stick=not saved)
        if saved:
            await chat.restore_scroll(saved)
        hdr = self.query_one("#header", HeaderBar)
        hdr.session = self._session_name
        st = self.query_one("#status", StatusBar)
        st.session = self._session_name
        st.mode = "idle"
        try:
            self.query_one("#composer", Composer).set_history(
                [str(m.get("content", "")) for m in restored if m.get("role") == "user"])
        except Exception:
            pass
        self._refresh_ctx()
        self._refresh_recent()
        self._sync_title()
        if rendered:
            await chat.add_notice(f"已载入会话 {self._session_name}")
        else:
            # 空会话：保留欢迎首屏（含「继续上次会话」卡片），只用轻提示回报
            self._toast(glyph("ok") + f" 已切到空会话 {self._session_name}")

    async def action_quit_app(self) -> None:
        self.exit()

    async def action_toggle_statusbar(self) -> None:
        sb = self.query_one("#status", StatusBar)
        sb.display = not sb.display

    async def action_open_help(self) -> None:
        self.push_screen(HelpModal(self._help_sections()))

    def _help_sections(self) -> dict[str, str]:
        sections: dict[str, str] = {}

        keys = ["## 快捷键", ""]
        for key, desc in [
            ("Ctrl+N", "新会话"),
            ("Ctrl+S", "开合侧栏"),
            ("Ctrl+E", "命令面板"),
            ("Ctrl+T", "切换主题"),
            ("Ctrl+X", "切换会话"),
            ("Ctrl+U", "会话用量"),
            ("Ctrl+R", "搜索当前对话"),
            ("F3 / Shift+F3", "下一处 / 上一处命中"),
            ("Ctrl+Y", "复制上一条回答"),
            ("Ctrl+End", "回到底部"),
            ("Ctrl+L", "清屏"),
            ("Ctrl+Q", "退出"),
            ("F1", "帮助浮层"),
            ("F2", "状态条开关"),
            ("Enter", "发送"),
            ("Shift+Enter", "换行"),
            ("Esc", "中断回复 / 关闭浮层"),
        ]:
            keys.append(f"- **{key}** — {desc}")
        sections["快捷键"] = "\n".join(keys)

        cmds = ["## 斜杠命令", ""]
        try:
            from ..slash import REGISTRY
            for name in sorted(REGISTRY):
                cmds.append(f"- **/{name}** — {REGISTRY[name]['description']}")
        except Exception:
            cmds.append("（命令注册表不可用）")
        cmds += ["", "## TUI 专属命令", "",
                 "- **/theme** — 打开主题选择器（Ctrl+T）",
                 "- **/usage** — 会话用量面板（Ctrl+U）",
                 "- **/status** — 运行状态面板（模型 / key / 渠道）",
                 "- **/search** — 跨会话检索浮层",
                 "- **/copy** — 复制上一条回答；/copy all 复制整段会话",
                 "- **/export [名字]** — 导出会话 Markdown 到 workspace/exports/",
                 "- **/sessions** — 会话切换浮层（Ctrl+X）"]
        sections["命令"] = "\n".join(cmds)

        tools = ["## 内置工具", ""]
        try:
            for d in _tools.tool_defs():
                fn = d.get("function", {})
                tools.append(f"- **{fn.get('name', '?')}** — {str(fn.get('description', ''))[:70]}")
        except Exception:
            tools.append("（工具注册表不可用）")
        sections["工具"] = "\n".join(tools)

        skills = ["## 技能", ""]
        try:
            for s in self.ws.skills:
                skills.append(f"- **{s.name}** — {getattr(s, 'description', '')}")
            if len(skills) == 2:
                skills.append("（还没有技能 — 试试 /skills，或让 agent 写一个）")
        except Exception:
            skills.append("（技能不可用）")
        sections["技能"] = "\n".join(skills)

        about = [
            "## 关于 uiu",
            "",
            f"- 版本 **v{_VERSION}**",
            f"- 工作区 {self.ws.root}",
            f"- 模型 {self._model_display()}",
            "- 会话 default（自动保存，重启即恢复）",
            "",
            "数据全部落在本地工作区：SOUL / MEMORY / skills 都是纯文本，随你改。",
        ]
        sections["关于"] = "\n".join(about)
        return sections

    def on_unmount(self) -> None:
        self._emit_alive = False
        try:
            from ..confirm import set_confirm_handler
            set_confirm_handler(None)
        except Exception:
            pass
        try:
            from ..clarify import set_ask_handler
            set_ask_handler(None)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Entry
# --------------------------------------------------------------------------


def run_app(
    client: Any,
    ws: Workspace,
    *,
    model: str = "",
    cfg: Any = None,
    app_cfg: Any = None,
    turn_runner: Any = None,
    theme_name: str = DEFAULT_THEME,
) -> int:
    """Entry point used by main.py: runs the textual app, returns exit code."""
    app = UiuApp(client, ws, model=model, cfg=cfg, app_cfg=app_cfg,
                 turn_runner=turn_runner, theme_name=theme_name)
    try:
        app.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
