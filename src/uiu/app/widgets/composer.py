"""Composer: 多行输入区（Enter 发送 / Shift+Enter 换行 / slash 补全）。"""

from __future__ import annotations

from typing import Any, Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static, TextArea

from ..theme import glyph


def _describe(word: str) -> str:
    """Look up a slash command's description for the completion menu."""
    if not word.startswith("/"):
        return ""
    try:
        from ...slash import REGISTRY
        entry = REGISTRY.get(word[1:].split()[0])
        if entry:
            return str(entry.get("description", ""))
    except Exception:
        pass
    return ""


class SendArea(TextArea):
    """TextArea where Enter submits and Shift+Enter inserts a newline."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class EscPressed(Message):
        """Sent when Esc is pressed (busy => cancel)."""

    BINDINGS = [
        Binding("enter", "submit_send", "Send (Enter)", priority=True),
        Binding("shift+enter", "insert_newline", "Newline"),
        Binding("escape", "esc", "Cancel/close", priority=True),
    ]

    # 超长粘贴折叠阈值
    PASTE_LINES = 6
    PASTE_CHARS = 600

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pastes: dict[str, str] = {}

    async def _on_paste(self, event: events.Paste) -> None:
        """折叠大段粘贴：输入框只留一行占位符，发送时自动还原全文。"""
        text = event.text or ""
        lines = text.count("\n") + 1
        if len(text) > self.PASTE_CHARS or lines > self.PASTE_LINES:
            key = f"[粘贴 {len(self._pastes) + 1} · {lines} 行 / {len(text)} 字]"
            self._pastes[key] = text
            self.insert(key, maintain_selection_offset=True)
            event.stop()
            return
        await super()._on_paste(event)

    def paste_count(self) -> int:
        return len(self._pastes)

    def expanded_text(self) -> str:
        """The composer text with collapsed pastes expanded back to full text."""
        text = self.text
        for key, full in self._pastes.items():
            text = text.replace(key, full)
        return text

    def clear_pastes(self) -> None:
        self._pastes.clear()

    def action_submit_send(self) -> None:
        text = self.expanded_text().strip()
        if text:
            self.post_message(self.Submitted(text))

    def action_insert_newline(self) -> None:
        self.insert("\n", maintain_selection_offset=True)

    def action_esc(self) -> None:
        self.post_message(self.EscPressed())


class SlashMenu(ListView):
    """Floating completion panel: command + one-line description."""

    DEFAULT_CSS = """
    SlashMenu {
        display: none;
        height: auto;
        max-height: 12;
        border: round $accent 55%;
        background: $surface;
        margin: 0 0 1 0;
        scrollbar-size-vertical: 1;
    }
    SlashMenu.-visible {
        display: block;
    }
    SlashMenu ListItem {
        padding: 0 1;
        background: transparent;
    }
    SlashMenu ListItem.-highlight {
        background: $accent 35%;
    }
    """

    def __init__(self, get_words: Callable[[str], list[str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._get_words = get_words
        self._items: list[str] = []

    async def refresh_items(self, prefix: str) -> None:
        words = self._get_words(prefix) if self._get_words else []
        self._items = words[:12]
        await self.clear()
        for w in self._items:
            desc = _describe(w)
            label = Label(w) if not desc else Label(f"{w:<16}[dim]{desc}[/dim]")
            await self.append(ListItem(label))
        self.set_classes("-visible" if self._items else "")
        if self._items:
            self.index = 0

    def hide(self) -> None:
        self.set_classes("")

    def is_visible_menu(self) -> bool:
        return self.has_class("-visible") and bool(self._items)

    def selected_word(self) -> str | None:
        if self.index is None or self.index >= len(self._items):
            return None
        return self._items[self.index]

    def move(self, delta: int) -> None:
        n = len(self._items)
        if not n:
            return
        idx = self.index if self.index is not None else 0
        self.index = (idx + delta) % n


class Composer(Vertical):
    """Bottom input area: prompt glyph + SendArea + slash menu + hint bar."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Cancelled(Message):
        """User pressed Esc while a turn was running."""

    DEFAULT_CSS = """
    Composer {
        height: auto;
        padding: 1 1 0 1;
        background: $panel;
    }
    Composer #composer-shell {
        height: auto;
        border: round $panel-lighten-1;
        background: $surface;
        padding: 0 1;
        align-vertical: top;
    }
    Composer #composer-shell:focus-within {
        border: round $accent 70%;
    }
    Composer #composer-shell.-busy {
        border: round $warning 70%;
    }
    Composer #composer-glyph {
        width: 2;
        height: 1;
        color: $accent;
        text-style: bold;
    }
    Composer #composer-glyph.-busy {
        color: $warning;
    }
    Composer SendArea {
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: transparent;
        border: none !important;
    }
    Composer #composer-hint-row {
        height: 1;
    }
    Composer #composer-hint {
        width: 1fr;
        height: 1;
        color: $text-muted;
    }
    Composer #composer-count {
        width: auto;
        height: 1;
        color: $text-muted;
    }
    """

    HINT_FULL = (
        glyph("hint") + " 发送  " + glyph("sep") + "  Shift+" + glyph("hint")
        + " 换行  " + glyph("sep") + "  / 命令  " + glyph("sep")
        + "  Ctrl+E 面板  " + glyph("sep") + "  F1 帮助"
    )
    HINT_MED = (
        glyph("hint") + " 发送  " + glyph("sep") + "  / 命令  " + glyph("sep")
        + "  Ctrl+E 面板  " + glyph("sep") + "  F1 帮助"
    )
    HINT_MIN = glyph("hint") + " 发送  " + glyph("sep") + "  / 命令  " + glyph("sep") + "  F1 帮助"

    HINT = HINT_FULL

    def __init__(self, get_words: Callable[[str], list[str]], *, agent_name: str = "agent",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._get_words = get_words
        self.agent_name = agent_name
        self._busy = False
        self._history: list[str] = []
        self._hist_pos: int | None = None
        self._draft = ""
        self._recalling = False
        self._suppress_menu_for: str | None = None
        self._activity = ""
        self._cancellable = True

    # -- history ---------------------------------------------------------

    def set_history(self, items: list[str]) -> None:
        """Seed the ↑/↓ recall buffer (e.g. from a resumed session)."""
        self._history = [str(i) for i in items if str(i).strip()][-200:]
        self._hist_pos = None

    def push_history(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self._history and self._history[-1] == text:
            return
        self._history.append(text)
        self._history = self._history[-200:]
        self._hist_pos = None

    def _recall(self, delta: int) -> bool:
        if not self._history:
            return False
        if self._hist_pos is None:
            if delta > 0:
                return False
            self._draft = self._input.text
            self._hist_pos = len(self._history) - 1
        else:
            pos = self._hist_pos + delta
            if pos < 0:
                pos = 0
            elif pos >= len(self._history):
                self._hist_pos = None
                self._set_text_quietly(self._draft)
                return True
            self._hist_pos = pos
        self._set_text_quietly(self._history[self._hist_pos])
        return True

    def _set_text_quietly(self, text: str) -> None:
        """Programmatic text change that must not pop the slash menu.

        The Changed message arrives asynchronously, so a boolean flag can be
        stale by then — remember the exact text we wrote instead.
        """
        self._recalling = True
        self._suppress_menu_for = text
        try:
            self._input.text = text
            self._input.move_cursor(self._input.document.end)
        finally:
            self._recalling = False

    def compose(self) -> ComposeResult:
        yield SlashMenu(self._get_words, id="slash-menu")
        with Horizontal(id="composer-shell"):
            yield Static(glyph("prompt"), id="composer-glyph")
            yield SendArea("", id="composer-input")
        with Horizontal(id="composer-hint-row"):
            yield Label(self.HINT, id="composer-hint")
            yield Label("", id="composer-count")

    async def on_mount(self) -> None:
        self._input = self.query_one("#composer-input", SendArea)
        self._menu = self.query_one("#slash-menu", SlashMenu)
        self._input.focus()

    def _hint(self) -> str:
        try:
            width = self.size.width or 100
        except Exception:
            width = 100
        if width < 64:
            return self.HINT_MIN
        if width < 96:
            return self.HINT_MED
        return self.HINT_FULL

    def on_resize(self, event: object) -> None:
        self._render_hint()

    def _show_count(self) -> bool:
        try:
            return (self.size.width or 100) >= 64
        except Exception:
            return True

    # -- send / cancel ---------------------------------------------------

    def on_send_area_submitted(self, event: SendArea.Submitted) -> None:
        if self._busy:
            return
        event.stop()
        # Enter with the slash menu open confirms the highlighted completion
        if self._menu.is_visible_menu():
            word = self._menu.selected_word()
            if word:
                self.accept_completion(word)
            return
        self.push_history(event.text)
        self.post_message(self.Submitted(event.text))

    async def on_send_area_esc_pressed(self, event: SendArea.EscPressed) -> None:
        event.stop()
        if self._menu.is_visible_menu():
            self._menu.hide()
            return
        if self._busy:
            self.post_message(self.Cancelled())
            return
        if self._input.text:
            # Esc clears the current input if non-empty; second Esc quits (app binding)
            self._input.text = ""
            return

    async def on_list_view_selected(self, event: Any) -> None:
        if self._menu.is_visible_menu() and event.list_view is self._menu:
            word = self._menu.selected_word()
            if word:
                self.accept_completion(word)
            self._menu.hide()

    async def on_key(self, event: Key) -> None:
        if self._menu.is_visible_menu() and event.key in ("up", "down"):
            self._menu.move(-1 if event.key == "up" else 1)
            event.stop()
            return
        # ↑/↓ recall previous prompts when the cursor is on a single-line draft
        if event.key in ("up", "down") and "\n" not in self._input.text:
            if self._recall(-1 if event.key == "up" else 1):
                event.stop()
                return
        if event.key == "tab" and self._menu.is_visible_menu():
            word = self._menu.selected_word()
            if word:
                self.accept_completion(word)
            self._menu.hide()
            event.stop()
            return
        if event.key == "tab" and self._input.text.startswith("/"):
            await self._menu.refresh_items(self._input.text)
            event.stop()
            return
        # Live completion as the user types a slash token
        if event.key and len(event.key) == 1 and self._should_show_menu():
            await self._menu.refresh_items(self._input.text)
        elif self._menu.is_visible_menu() and not self._should_show_menu():
            self._menu.hide()

    def _should_show_menu(self) -> bool:
        text = self._input.text
        return text.startswith("/") and " " not in text

    def accept_completion(self, word: str) -> None:
        self._input.text = word + " " if word.startswith("/") else word
        self._input.move_cursor(self._input.document.end)
        self._menu.hide()

    async def on_text_area_changed(self, event: Any) -> None:
        """Drive the slash menu live as the user types (Changed bubbles up)."""
        if event.text_area is not self._input:
            return
        self._update_count()
        if self._busy:
            return
        if self._suppress_menu_for is not None:
            # 程序化写入（历史回溯）：只消费一次，不弹补全
            same = self._input.text == self._suppress_menu_for
            self._suppress_menu_for = None
            if same or self._recalling:
                return
        if self._should_show_menu():
            await self._menu.refresh_items(self._input.text)
        elif self._menu.is_visible_menu():
            self._menu.hide()

    def _update_count(self) -> None:
        try:
            n = len(self._input.expanded_text())
            label = self.query_one("#composer-count", Label)
            if not self._show_count():
                label.update("")
                return
            n_pastes = self._input.paste_count()
            extra = f" · {n_pastes} 处折叠" if n_pastes else ""
            label.update(f"{n} 字{extra}" if n else "")
        except Exception:
            pass

    # -- state -----------------------------------------------------------

    def set_activity(self, activity: str) -> None:
        """Show what the agent is doing right now (tool name / stage)."""
        self._activity = activity or ""
        if self._busy:
            self._render_hint()

    def _render_hint(self) -> None:
        try:
            hint = self.query_one("#composer-hint", Label)
        except Exception:
            return
        if self._busy:
            text = "agent 思考中…"
            if self._activity:
                text += "   " + glyph("tool") + " " + self._activity
            text += "     Esc 中断" if self._cancellable else "     完成后自动返回"
            hint.update(text)
        else:
            hint.update(self._hint())

    def set_busy(self, busy: bool, *, cancellable: bool = True) -> None:
        """Lock the composer while work runs.

        cancellable=False is for work we cannot actually interrupt (slash
        commands) — the hint then stops promising Esc.
        """
        self._busy = busy
        self._cancellable = cancellable
        if not busy:
            self._activity = ""
        try:
            shell = self.query_one("#composer-shell")
            shell.set_class(busy, "-busy")
            self.query_one("#composer-glyph", Static).set_class(busy, "-busy")
        except Exception:
            pass
        self._render_hint()

    def clear(self) -> None:
        self._input.text = ""
        self._input.clear_pastes()
        self._menu.hide()
        self._update_count()

    def focus_input(self) -> None:
        self._input.focus()
