"""Composer: multiline input with Enter-to-send, Shift+Enter newline, and slash completion."""

from __future__ import annotations

from typing import Any, Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, TextArea


class SendArea(TextArea):
    """TextArea where Enter submits and Shift+Enter inserts a newline."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class EscPressed(Message):
        """Sent when Esc is pressed (busy => cancel)."""

    BINDINGS = [
        Binding('enter', 'submit_send', 'Send (Enter)', priority=True),
        Binding('shift+enter', 'insert_newline', 'Newline'),
        Binding('escape', 'esc', 'Cancel/close', priority=True),
    ]

    def action_submit_send(self) -> None:
        text = self.text.strip()
        if text:
            self.post_message(self.Submitted(text))

    def action_insert_newline(self) -> None:
        self.insert("\n", maintain_selection_offset=True)

    def action_esc(self) -> None:
        self.post_message(self.EscPressed())


class SlashMenu(ListView):
    """Small dropdown listing slash commands / tools / skills matching the token."""

    DEFAULT_CSS = """
    SlashMenu {
        display: none;
        height: auto;
        max-height: 10;
        border: round $accent;
        background: $surface;
    }
    SlashMenu.-visible {
        display: block;
    }
    """

    def __init__(self, get_words: Callable[[str], list[str]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._get_words = get_words
        self._items: list[str] = [];

    async def refresh_items(self, prefix: str) -> None:
        words = self._get_words(prefix) if self._get_words else []
        self._items = words[:12]
        await self.clear()
        for w in self._items:
            await self.append(ListItem(Label(w)))
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


class Composer(Vertical):
    """Bottom input area: SendArea + slash menu + hint."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Cancelled(Message):
        """User pressed Esc while a turn was running."""

    DEFAULT_CSS = """
    Composer {
        height: auto;
        border-top: solid $primary;
        padding: 0 1;
        background: $surface;
    }
    Composer SendArea {
        height: auto;
        max-height: 8;
        padding: 0 1;
    }
    Composer #composer-hint {
        color: $text-muted;
        padding: 0 0 1 0;
        height: 1;
    }
    """

    def __init__(self, get_words: Callable[[str], list[str]], *, agent_name: str = "agent", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._get_words = get_words
        self.agent_name = agent_name
        self._busy = False

    def compose(self) -> ComposeResult:
        yield SendArea("", id="composer-input")
        yield SlashMenu(self._get_words, id="slash-menu")
        yield Label(self._hint(), id="composer-hint")

    def _hint(self) -> str:
        return "Enter 发送 · Shift+Enter 换行 · ctrl+e 命令面板 · /help"

    async def on_mount(self) -> None:
        self._input = self.query_one("#composer-input", SendArea)
        self._menu = self.query_one("#slash-menu", SlashMenu)
        self._input.focus()

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
        if event.key == "tab" and self._menu.is_visible_menu():
            word = self._menu.selected_word()
            if word:
                self.accept_completion(word)
            self._menu.hide()
            event.stop()
            return
        if event.key == "tab" and self._input.text.startswith("/"):
            self._menu.refresh_items(self._input.text)
            event.stop()
            return
        # Live completion as the user types a slash token
        if event.key and len(event.key) == 1 and self._should_show_menu():
            self._menu.refresh_items(self._input.text)
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
        if self._busy:
            return
        if self._should_show_menu():
            await self._menu.refresh_items(self._input.text)
        elif self._menu.is_visible_menu():
            self._menu.hide()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        hint = self.query_one("#composer-hint", Label)
        hint.update("agent 思考中… Esc 中断" if busy else self._hint())

    def clear(self) -> None:
        self._input.text = ""
        self._menu.hide()

    def focus_input(self) -> None:
        self._input.focus()