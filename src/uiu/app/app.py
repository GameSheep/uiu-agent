"""UiuApp: full-screen textual application for uiu agent conversations."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Markdown, Static

from .. import __version__ as _VERSION
from .. import tools as _tools
from ..workspace import Workspace, load_workspace

from .agent_worker import agent_turn
from .clarify_bridge import AskUser, ClarifyBridge
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

    def __init__(self, markdown: str) -> None:
        super().__init__()
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield Static("帮助 — Esc 关闭", classes="help-title")
            yield Markdown(self._markdown)
            yield Button("关闭 (Esc)", id="help-close", variant="primary")

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-box {
        width: 78%;
        height: 82%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #help-box .help-title {
        text-style: bold;
        color: $accent;
    }
    #help-box Markdown {
        height: 1fr;
    }
    """

    def _on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.stop()
        else:
            super()._on_key(event)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss(None)


class ConfirmModal(ModalScreen[bool]):
    """Inline confirmation modal (sensitive actions / clarify choices)."""

    def __init__(self, question: str, options: list[str] | None = None) -> None:
        super().__init__()
        self.question = question
        self.options = options or []

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self.question, classes="confirm-text")
            for i, opt in enumerate(self.options[:6], 1):
                yield Button(f"{i}. {opt}", id=f"opt-{i}", variant="default")
            if not self.options:
                with Horizontal():
                    yield Button("确认", id="opt-yes", variant="error")
                    yield Button("取消", id="opt-no", variant="primary")

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    #confirm-box {
        width: 64;
        padding: 2 3;
        border: round $accent;
        background: $surface;
    }
    #confirm-box Button {
        margin: 1 1 0 0;
    }
    """

    def _answer(self, text: str) -> None:
        self.dismiss(text)

    def _on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss("")
            event.stop()
        elif self.options and event.key.isdigit():
            n = int(event.key)
            if 1 <= n <= len(self.options):
                self._answer(self.options[n - 1])
            event.stop()
        else:
            super()._on_key(event)

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



# --------------------------------------------------------------------------
# Command palette: a simple modal with an Input + fuzzy list of slash commands
# --------------------------------------------------------------------------


class CommandPalette(ModalScreen[str]):
    """Type-ahead modal listing slash commands; Enter runs the selected one."""

    def __init__(self, words: list[str]) -> None:
        super().__init__()
        self.words = words
        self._matches: list[str] = words

    def compose(self) -> ComposeResult:
        from textual.widgets import Input, ListItem, ListView
        with Vertical(id="palette-box"):
            yield Static("命令面板 — 输入过滤，↑↓ 选择，Enter 运行", classes="help-title")
            yield Input(placeholder="type a command…", id="palette-input")
            self._lv = ListView(id="palette-list")
            yield self._lv

    DEFAULT_CSS = """
    CommandPalette {
        align: center middle;
    }
    #palette-box {
        width: 60;
        height: 60%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    #palette-box .help-title {
        text-style: bold;
        color: $accent;
        margin: 0 0 1 0;
    }
    #palette-box Input {
        margin: 0 0 1 0;
    }
    #palette-list {
        height: 1fr;
    }
    """

    async def on_mount(self) -> None:
        await self._render(self.words)
        self.query_one("#palette-input", Input).focus()

    async def _render(self, words: list[str]) -> None:
        from textual.widgets import ListItem
        self._matches = words
        lv = self.query_one("#palette-list", ListView)
        await lv.clear()
        for w in words[:20]:
            await lv.append(ListItem(Label(w)))

    async def on_input_changed(self, event: Any) -> None:
        q = (self.query_one("#palette-input", Input).value or "").strip().lower()
        matches = [w for w in self.words if q in w.lower()] if q else self.words
        await self._render(matches)

    async def on_list_view_selected(self, event: Any) -> None:
        lv = self.query_one("#palette-list", ListView)
        if lv.index is not None and lv.index < len(self._matches):
            self.dismiss(self._matches[lv.index])

    def _on_key(self, event: Any) -> None:
        if event.key == "escape":
            self.dismiss("")
            event.stop()
        elif event.key == "enter":
            lv = self.query_one("#palette-list", ListView)
            if lv.index is not None and lv.index < len(self._matches):
                self.dismiss(self._matches[lv.index])
            event.stop()
        else:
            super()._on_key(event)


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
    }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_chat", "新会话", show=False),
        Binding("ctrl+s", "toggle_sidebar", "侧栏", show=False),
        Binding("ctrl+r", "history_search", "历史搜索", show=False),
        Binding("ctrl+l", "clear_screen", "清屏", show=False),
        Binding("ctrl+e", "command_palette", "命令面板", show=False),
        Binding("ctrl+q", "quit_app", "退出", show=False),
        Binding("f2", "toggle_statusbar", "状态条", show=False),
        Binding("question_mark", "open_help", "帮助", show=False),
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
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.client = client
        self.ws = ws
        self.model = model
        self.cfg = cfg
        self.app_cfg = app_cfg
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
        self._pending_tool_name = ""
        self._turn_runner = turn_runner if turn_runner is not None else agent_turn
        self._worker = None

    # -- lifecycle -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        with Horizontal(id="main-row"):
            yield SideBar(id="sidebar")
            yield ChatView(self._agent_name, id="chat")
        yield Composer(self._slash_words, id="composer")
        yield StatusBar(id="status")

    async def on_mount(self) -> None:
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
        st = self.query_one("#status", StatusBar)
        st.agent = self._agent_name
        st.model = self._model_display()
        st.tools_n = n_tools
        st.skills_n = n_skills

        # tool schemas: builtins + skills
        self._tool_schemas = self._rebuild_schemas()

        # message history: auto-resume default session if any
        prev = None
        try:
            from .. import sessions as _sessions
            self._sessions = _sessions
            prev = _sessions.load_session(self.ws.root, "default")
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

        self._refresh_ctx()
        # sidebar collapsed by default (ctrl+s to open)
        try:
            self.query_one("#sidebar").display = False
        except Exception:
            pass
        if prev and len(prev) > 1:
            chat = self.query_one("#chat", ChatView)
            await chat.add_notice("已恢复上次会话（/new 开新会话）")
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
        st.turns = sum(1 for m in self._messages if m.get("role") == "user")
        chars = self._context_chars()
        st.ctx_pct = min(99, int((chars or 0) / 1200))

    # -- event handlers from the worker ----------------------------------

    async def on_text_chunk(self, event: TextChunk) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.stream(event.delta)

    async def on_tool_call_event(self, event: ToolCallEvent) -> None:
        # Tool start shown implicitly by the result row; we only surface results.
        self._pending_tool_name = event.name

    async def on_tool_result_event(self, event: ToolResultEvent) -> None:
        chat = self.query_one("#chat", ChatView)
        ok = not (event.result or "").startswith("[error]")
        one = " ".join((event.result or "").split())
        preview = one[:120]
        if len(one) > 120:
            preview += "…"
        await chat.add_tool(event.name, ok, preview)

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
        self._autosave()
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
        err = event.error
        hint = ""
        msg = str(err)
        tn = type(err).__name__
        if "401" in msg or "invalid_api_key" in msg.lower() or "AuthenticationError" in tn:
            hint = "\n\n→ API key 无效：运行 `uiu config --api-key <key>` 或 `uiu model` 更换"
        elif "context_length" in msg.lower() or "maximum context" in msg.lower():
            hint = "\n\n→ 对话太长：输入 /clear 清空后重试"
        await chat.add_error(f"[error] {tn}: {msg[:300]}{hint}")
        self._autosave()

    async def on_interrupted(self, event: Interrupted) -> None:
        self._turn_running = False
        chat = self.query_one("#chat", ChatView)
        await chat.finish_assistant()
        await chat.add_notice("(已中断)")
        composer = self.query_one("#composer", Composer)
        composer.set_busy(False)
        composer.clear()
        composer.focus_input()
        st = self.query_one("#status", StatusBar)
        st.mode = "idle"
        self._autosave()

    async def on_ask_user(self, event: AskUser) -> None:
        """Clarify bridge: show modal, hand answer back to the waiting thread."""
        answer = await self.push_screen_wait(ConfirmModal(event.question, event.options))
        self._bridge.answer(answer if answer is not None else "")

    # -- sending a user turn --------------------------------------------

    async def _send(self, text: str) -> None:
        if self._turn_running:
            return
        chat = self.query_one("#chat", ChatView)
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
        await chat.begin_assistant()

        composer = self.query_one("#composer", Composer)
        composer.set_busy(True)
        st = self.query_one("#status", StatusBar)
        st.mode = "running"

        import threading
        self._cancel = threading.Event()
        cancel_ev = self._cancel

        def emit(msg: Any) -> None:
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

    async def _dispatch_slash(self, text: str):
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
        handled, quit_sig = dispatch(text, sctx)
        self.ws = sctx.ws
        self._tool_schemas = self._rebuild_schemas()
        chat = self.query_one("#chat", ChatView)
        for line in say_out:
            if line.strip():
                await chat.add_notice(line.replace("\n", "\n\n"))
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
            await chat.add_notice("(中断请求已发送…)")

    async def on_chat_view_suggestion_picked(self, event: ChatView.SuggestionPicked) -> None:
        event.stop()
        composer = self.query_one("#composer", Composer)
        composer.clear()
        await self._send(event.text)

    # -- session & autosave ----------------------------------------------

    def _autosave(self) -> None:
        if self._sessions is None:
            return
        try:
            self._sessions.save_session(self.ws.root, "default", self._messages)
        except Exception:
            pass

    # -- actions ----------------------------------------------------------

    async def action_new_chat(self) -> None:
        if self._turn_running:
            return
        if self._sessions is not None:
            try:
                self._sessions.save_session(self.ws.root, "default", self._messages)
            except Exception:
                pass
        self._messages = [{"role": "system", "content": self.ws.system_prompt()}]
        chat = self.query_one("#chat", ChatView)
        await chat.clear_chat()
        self._refresh_ctx()
        composer = self.query_one("#composer", Composer)
        composer.focus_input()

    async def action_toggle_sidebar(self) -> None:
        sb = self.query_one("#sidebar", SideBar)
        sb.display = not sb.display

    async def action_history_search(self) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.add_notice("(检索已保存会话 — 输入 /search <关键词>)")

    async def action_clear_screen(self) -> None:
        chat = self.query_one("#chat", ChatView)
        await chat.clear_chat()
        await chat.add_notice("(已清屏 — 对话上下文保留；/clear 清空上下文)")

    async def action_command_palette(self) -> None:
        words = self._slash_words()
        if not words:
            return
        result = await self.push_screen_wait(CommandPalette(words))
        if result:
            await self._send(result)

    async def action_quit_app(self) -> None:
        self.exit()

    async def action_toggle_statusbar(self) -> None:
        sb = self.query_one("#status", StatusBar)
        sb.display = not sb.display

    async def action_open_help(self) -> None:
        await self.push_screen(HelpModal(self._help_markdown()))

    def _help_markdown(self) -> str:
        lines = ["## 快捷键", ""]
        key_help = [
            ("ctrl+n", "新会话"),
            ("ctrl+s", "开合侧栏"),
            ("ctrl+r", "历史搜索"),
            ("ctrl+e", "命令面板"),
            ("ctrl+l", "清屏"),
            ("f2", "状态条开关"),
            ("?", "本帮助"),
        ]
        for key, desc in key_help:
            lines.append(f"- `{key}` — {desc}")
        lines += ["", "输入区：Enter 发送 · Shift+Enter 换行 · Esc 中断/取消", "", "## 斜杠命令", ""]
        try:
            from ..slash import REGISTRY
            for name in sorted(REGISTRY):
                lines.append(f"- `/{name}` — {REGISTRY[name]['description']}")
        except Exception:
            pass
        lines += ["", "Enter 发送 · Shift+Enter 换行 · Esc 中断。"]
        return "\n".join(lines)

    async def on_side_bar_command_picked(self, event: SideBar.CommandPicked) -> None:
        event.stop()
        await self._send(event.command)

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
) -> int:
    """Entry point used by main.py: runs the textual app, returns exit code."""
    app = UiuApp(client, ws, model=model, cfg=cfg, app_cfg=app_cfg,
                 turn_runner=turn_runner)
    try:
        app.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        import traceback
        traceback.print_exc()
        return 1
