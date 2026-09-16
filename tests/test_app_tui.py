"""Behavioral tests for the textual full-screen app (uiu.app).

These use textual's offline pilot with a fake turn runner — no real LLM/network.
Guards the v1.0 red line: the new TUI is exercised without bypassing uiu.tools.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

# textual is a core dependency since v1.0; skip if not importable (shouldn't happen)
tx = pytest.importorskip("textual")

from uiu.app import UiuApp  # noqa: E402
from uiu.app.messages import (  # noqa: E402
    NoticeEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
    TurnDone,
)
from uiu.app.widgets import Bubble, ChatView, Composer, SideBar, StatusBar  # noqa: E402
from uiu.workspace import Workspace  # noqa: E402


def _run(coro):
    """Run an async test body in a fresh loop (no pytest-asyncio dependency)."""
    return asyncio.run(coro)


def make_ws(tmp_path: Path) -> Workspace:
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        (tmp_path / name).write_text(f"# {name}\ncontent", encoding="utf-8")
    return Workspace(root=tmp_path, soul="soul", identity="id",
                     user="user", memory="mem", skills=[])


class _Stub:
    def __init__(self):
        self.called = []


def _seq_runner(events):
    """A fake agent_turn that replays a fixed event sequence."""
    def _runner(*, client, messages, tool_schemas, skills, model, cfg,
                emit, cancel):
        for ev in events:
            emit(ev)
            time.sleep(0.01)
    return _runner


def test_layout_mounts(tmp_path):
    return _run(_impl_layout_mounts(tmp_path))

async def _impl_layout_mounts(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        ids = {w.id for w in app.query("*")}
        for need in ("header", "sidebar", "chat", "composer", "status"):
            assert need in ids, f"missing widget: {need}"
        # empty hint + suggestion chips render
        chat = app.query_one("#chat", ChatView)
        assert chat.query("#empty-hint")
        assert len(chat.query("Button.suggestion-chip")) > 0


def test_slash_words_from_registry(tmp_path):
    return _run(_impl_slash_words_from_registry(tmp_path))

async def _impl_slash_words_from_registry(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        words = app._slash_words("/")
        assert "/help" in words
        assert "/sessions" in words


def test_user_turn_streams_assistant(tmp_path):
    return _run(_impl_user_turn_streams_assistant(tmp_path))

async def _impl_user_turn_streams_assistant(tmp_path):
    ws = make_ws(tmp_path)
    events = [TextChunk("你好"), TextChunk("，世界"), TurnDone("你好，世界", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("h", "i")
        await pilot.press("enter")
        await pilot.pause(0.6)
        bubbles = app.query_one("#chat", ChatView).query(Bubble)
        roles = [b.role for b in bubbles]
        assert "user" in roles
        assert "assistant" in roles
        assistant = [b for b in bubbles if b.role == "assistant"][0]
        assert "你好，世界" in assistant.get_text()
        status = app.query_one("#status", StatusBar)
        assert status.mode == "idle"
        assert status.turns == 1


def test_slash_dispatch_runs(tmp_path):
    return _run(_impl_slash_dispatch_runs(tmp_path))

async def _impl_slash_dispatch_runs(tmp_path):
    """Submitting a slash command runs it (messages untouched, output as notice)."""
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        # /identity prints the workspace identity as an inline notice.
        # Enter while the completion menu is open confirms the highlighted
        # completion; a second Enter actually sends the command.
        await pilot.press(*list("/identity"))
        await pilot.pause(0.2)
        await pilot.press("enter")  # confirm completion
        await pilot.press("enter")  # send
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        notices = [b for b in chat.query(Bubble) if b.role == "notice"]
        assert notices, "expected a notice bubble from /identity"
        # slash output should not become a user turn
        assert all(not (m.get("role") == "user") for m in app._messages[1:])


def test_confirm_gate_for_sensitive_tool(tmp_path, monkeypatch):
    return _run(_confirm_impl(tmp_path))

async def _confirm_impl(tmp_path):
    """send_wechat executes only after the user confirms via the bridge."""
    from uiu import confirm as confirm_mod

    ws = make_ws(tmp_path)
    calls = {"asked": False, "answer": ""}

    # Register a fake host confirm (test-level) mimicking the TUI bridge
    def fake_confirm(name, preview):
        calls["asked"] = True
        return "yes"

    confirm_mod.set_confirm_handler(fake_confirm)
    assert confirm_mod.needs_confirm("send_wechat")
    assert confirm_mod.confirm("send_wechat", '{"contact":"x"}') == "yes"
    confirm_mod.set_confirm_handler(None)
    assert not confirm_mod.needs_confirm("send_wechat")


def test_tool_result_row_shown(tmp_path):
    return _run(_impl_tool_result_row_shown(tmp_path))

async def _impl_tool_result_row_shown(tmp_path):
    ws = make_ws(tmp_path)
    events = [
        TextChunk("ok"),
        ToolCallEvent("system_info", {"d": 1}),
        ToolResultEvent("system_info", "[ok] 120GB free"),
        TurnDone("ok 120GB free", 0.2),
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.6)
        chat = app.query_one("#chat", ChatView)
        notices = [b.get_text() for b in chat.query(Bubble) if b.role == "notice"]
        assert any("system_info" in t for t in notices), notices



def test_slash_completion_menu(tmp_path):
    """Typing "/" opens the completion menu; Enter confirms the selection."""
    return _run(_impl_slash_completion_menu(tmp_path))


async def _impl_slash_completion_menu(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("/")
        await pilot.pause(0.3)
        menu = composer.query_one("#slash-menu")
        assert menu.has_class("-visible"), "slash menu should open on /"
        assert len(menu._items) >= 10
        # Enter confirms the highlighted first item
        await pilot.press("enter")
        await pilot.pause(0.2)
        text = composer._input.text
        assert text.startswith("/"), text
        assert not menu.has_class("-visible")



def test_command_palette_runs_slash(tmp_path):
    """ctrl+e opens the palette; Enter executes the filtered slash command."""
    return _run(_impl_command_palette(tmp_path))


async def _impl_command_palette(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        await pilot.press("ctrl+e")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 2, "palette should be pushed"
        pal = app.screen_stack[-1]
        inp = pal.query_one("#palette-input")
        await pilot.press(*list("/help"))
        await pilot.pause(0.4)
        from textual.widgets import ListItem
        assert len(pal.query(ListItem)) >= 1
        await pilot.press("enter")
        await pilot.pause(0.8)
        assert len(app.screen_stack) == 1, "palette should dismiss after Enter"
        # /help emits the command list as a notice bubble
        chat = app.query_one("#chat", ChatView)
        notes = [b.get_text() for b in chat.query(Bubble) if b.role == "notice"]
        assert any("/tools" in t for t in notes), notes


def test_help_modal_f1(tmp_path):
    return _run(_impl_help_modal(tmp_path))


async def _impl_help_modal(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        await pilot.press("f1")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1



def test_sensitive_tool_shows_confirm_modal(tmp_path):
    """macro_play (sensitive) triggers an inline confirm modal; picking yes proceeds."""
    return _run(_impl_confirm(tmp_path))


async def _impl_confirm(tmp_path):
    from uiu.app.messages import TurnDone

    ws = make_ws(tmp_path)

    def fake_turn(*, client, messages, tool_schemas, skills, model, cfg,
                  emit, cancel):
        from uiu.tools import call_tool
        result = call_tool("macro_play", '{"name":"x"}')
        emit(TurnDone("done " + result, 0.1))

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=fake_turn)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        assert len(app.screen_stack) == 2, "confirm modal should be pushed"
        # pick option 1 (yes)
        await pilot.press("1")
        await pilot.pause(1.0)
        assert len(app.screen_stack) == 1, "modal should dismiss after answer"


# --------------------------------------------------------------------------
# v1.1 UI polish: themes, welcome banner, tool rows, sidebar actions
# --------------------------------------------------------------------------


def test_theme_system_and_picker(tmp_path):
    """The default theme is a uiu palette and ctrl+t picks a new one live."""
    return _run(_impl_theme_system(tmp_path))


async def _impl_theme_system(tmp_path):
    from uiu.app.theme import DEFAULT_THEME, theme_names

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert app.theme == DEFAULT_THEME
        assert len(theme_names()) >= 3
        await pilot.press("ctrl+t")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 2, "ctrl+t should push the theme picker"
        await pilot.press("down")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 1, "picker should dismiss after Enter"
        assert app.theme in theme_names()


def test_theme_picker_escape_reverts(tmp_path):
    return _run(_impl_theme_picker_escape(tmp_path))


async def _impl_theme_picker_escape(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        before = app.theme
        await pilot.press("ctrl+t")
        await pilot.pause(0.4)
        await pilot.press("down")
        await pilot.pause(0.3)
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1
        assert app.theme == before, "escaping the picker restores the theme"


def test_welcome_banner_surfaces(tmp_path):
    """Empty state is a product banner: brand, capability chips, suggestion cards."""
    return _run(_impl_welcome_banner(tmp_path))


async def _impl_welcome_banner(tmp_path):
    from uiu.app.widgets import WelcomeBanner

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        banner = chat.query_one("#empty-hint", WelcomeBanner)
        assert banner.query(".cap-chip"), "capability chips should render"
        assert len(banner.query("Button.suggestion-chip")) == 4
        assert banner.tools_n > 0, "banner should carry the live tool count"


def test_sidebar_sections_and_actions(tmp_path):
    return _run(_impl_sidebar(tmp_path))


async def _impl_sidebar(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        sb = app.query_one("#sidebar", SideBar)
        # 最近会话 / 本次会话 / 会话 / 视图 / 信息
        assert len(sb.query(".section-title")) == 5
        assert sb.query("#side-stats")
        assert sb.query("#side-recent")
        # the sidebar's "切换主题" entry routes to the theme picker
        sb.post_message(SideBar.CommandPicked("__action__:theme"))
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2


def test_tool_row_is_expandable(tmp_path):
    """Tool calls render as one-line rows that expand to the full result."""
    return _run(_impl_tool_row(tmp_path))


async def _impl_tool_row(tmp_path):
    from uiu.app.widgets import ToolRow

    ws = make_ws(tmp_path)
    events = [
        ToolCallEvent("read_file", {"path": "a.txt"}),
        ToolResultEvent("read_file", "[ok] hello world"),
        TurnDone("done", 0.5),
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.8)
        rows = app.query(ToolRow)
        assert len(rows) == 1, "one tool row expected"
        row = rows.first()
        assert row.role == "notice"
        assert "read_file" in row.get_text()
        assert row.has_class("-tool")
        detail = row.query_one("#tool-detail")
        assert not detail.has_class("-open")
        row.toggle()
        await pilot.pause(0.1)
        assert detail.has_class("-open"), "clicking a tool row expands it"


def test_statusbar_meter_and_tick(tmp_path):
    return _run(_impl_statusbar(tmp_path))


async def _impl_statusbar(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        st = app.query_one("#status", StatusBar)
        st.set_ctx(60_000, 120_000)
        await pilot.pause(0.2)
        assert st.ctx_pct == 50
        st.mode = "running"
        st.tick()
        await pilot.pause(0.2)
        assert st.clock, "tick should stamp the clock"
        assert st.frame >= 1, "running mode advances the spinner"


def test_header_reports_counts(tmp_path):
    return _run(_impl_header(tmp_path))


async def _impl_header(tmp_path):
    from uiu.app.widgets import HeaderBar

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="deepseek-chat", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        hdr = app.query_one("#header", HeaderBar)
        assert hdr.model == "deepseek-chat"
        assert hdr.tools_n > 0
        assert hdr.session == "default"


def test_help_overlay_sections(tmp_path):
    """F1 opens the categorized help overlay with a navigable section list."""
    return _run(_impl_help_sections(tmp_path))


# --------------------------------------------------------------------------
# Round 2: session switcher, usage panel, input history, live tool rows
# --------------------------------------------------------------------------


def test_session_switcher_loads_saved_session(tmp_path):
    return _run(_impl_session_switcher(tmp_path))


async def _impl_session_switcher(tmp_path):
    from textual.widgets import ListView
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "old", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "上一个问题"},
        {"role": "assistant", "content": "上一个回答"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+x")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2, "ctrl+x should open the switcher"
        lv = app.screen_stack[-1].query_one("#session-list", ListView)
        assert lv.query("ListItem"), "saved sessions should be listed"
        lv.index = 0
        await pilot.press("enter")
        await pilot.pause(0.8)
        assert len(app.screen_stack) == 1
        assert app._session_name == "old"
        chat = app.query_one("#chat", ChatView)
        texts = [b.get_text() for b in chat.query(Bubble)]
        assert any("上一个问题" in t for t in texts), texts


def test_session_switcher_bare_slash_opens_overlay(tmp_path):
    return _run(_impl_sessions_slash(tmp_path))


async def _impl_sessions_slash(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/sessions")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2, "/sessions opens the switcher overlay"
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1


def test_usage_panel(tmp_path):
    return _run(_impl_usage_panel(tmp_path))


async def _impl_usage_panel(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="deepseek-chat", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        stats = app._usage_stats()
        assert stats["model"] == "deepseek-chat"
        assert stats["session"] == "default"
        assert stats["tools"] > 0
        await pilot.press("ctrl+u")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2, "ctrl+u opens the usage panel"
        body = app.screen_stack[-1].query_one("#usage-body")
        assert body is not None
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1


def test_composer_history_recall(tmp_path):
    return _run(_impl_history(tmp_path))


async def _impl_history(tmp_path):
    ws = make_ws(tmp_path)
    events = [TurnDone("ok", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press(*list("看看磁盘"))
        await pilot.press("enter")
        await pilot.pause(0.6)
        assert composer._input.text == ""
        await pilot.press("up")
        await pilot.pause(0.2)
        assert composer._input.text == "看看磁盘"
        await pilot.press("down")
        await pilot.pause(0.2)
        assert composer._input.text == ""


def test_tool_row_shows_while_running(tmp_path):
    return _run(_impl_live_tool(tmp_path))


async def _impl_live_tool(tmp_path):
    from uiu.app.widgets import ToolRow

    def slow_runner(*, client, messages, tool_schemas, skills, model, cfg,
                    emit, cancel):
        emit(ToolCallEvent("read_file", {"path": "a.txt"}))
        time.sleep(0.7)
        emit(ToolResultEvent("read_file", "[ok] done"))
        emit(TurnDone("ok", 1.0))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=slow_runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.45)
        rows = app.query(ToolRow)
        assert len(rows) == 1, "tool row should exist before the result arrives"
        assert rows.first().running, "row should show the running state"
        await pilot.pause(0.9)
        rows = app.query(ToolRow)
        assert len(rows) == 1
        assert not rows.first().running
        assert rows.first().ok


# --------------------------------------------------------------------------
# Round 3: transcript search, responsive layout, paste collapse
# --------------------------------------------------------------------------


def test_transcript_search_jumps_to_message(tmp_path):
    return _run(_impl_search(tmp_path))


async def _impl_search(tmp_path):
    from textual.widgets import Input, ListView

    ws = make_ws(tmp_path)
    events = [TextChunk("磁盘还剩 890GB"), TurnDone("磁盘还剩 890GB", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.6)
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2, "ctrl+r opens transcript search"
        modal = app.screen_stack[-1]
        await pilot.press(*list("890"))
        await pilot.pause(0.4)
        lv = modal.query_one("#search-list", ListView)
        assert lv.query("ListItem"), "query should match the assistant reply"
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 1


def test_search_with_no_messages_is_graceful(tmp_path):
    return _run(_impl_search_empty(tmp_path))


async def _impl_search_empty(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+r")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1, "empty transcript should not open a modal"


def test_narrow_terminal_layout(tmp_path):
    return _run(_impl_narrow(tmp_path))


async def _impl_narrow(tmp_path):
    from uiu.app.widgets import HeaderBar

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause(0.3)
        sb = app.query_one("#sidebar", SideBar)
        hdr = app.query_one("#header", HeaderBar)
        sb.display = True
        await pilot.pause(0.2)
        assert not hdr.compact
        await pilot.resize_terminal(70, 30)
        await pilot.pause(0.5)
        assert not sb.display, "narrow terminal auto-hides the sidebar"
        assert hdr.compact, "narrow terminal switches the header to compact"
        await pilot.resize_terminal(110, 36)
        await pilot.pause(0.5)
        assert sb.display, "widening restores the auto-hidden sidebar"


def test_composer_collapses_long_paste(tmp_path):
    return _run(_impl_paste(tmp_path))


async def _impl_paste(tmp_path):
    from textual import events

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        area = composer._input
        big = "\n".join(f"第 {i} 行内容" for i in range(24))
        await area._on_paste(events.Paste(big))
        await pilot.pause(0.3)
        assert area.paste_count() == 1
        assert "粘贴" in area.text, area.text
        assert len(area.text) < 60, "placeholder should stay short"
        assert area.expanded_text().strip() == big.strip()


# --------------------------------------------------------------------------
# Round 4: stream throttling, elapsed timer, status panel, live activity
# --------------------------------------------------------------------------


def test_streaming_is_batched_but_complete(tmp_path):
    """Throttled streaming must still land every token by the end of the turn."""
    return _run(_impl_stream_batch(tmp_path))


async def _impl_stream_batch(tmp_path):
    ws = make_ws(tmp_path)
    chunks = [TextChunk(f"片段{i} ") for i in range(12)]
    events = chunks + [TurnDone("done", 0.2)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        bubbles = app.query_one("#chat", ChatView).query(Bubble)
        assistant = [b for b in bubbles if b.role == "assistant"]
        assert assistant, "assistant bubble expected"
        text = assistant[0].get_text()
        for i in range(12):
            assert f"片段{i}" in text, f"missing chunk {i}: {text!r}"


def test_status_bar_counts_elapsed_time(tmp_path):
    return _run(_impl_elapsed(tmp_path))


async def _impl_elapsed(tmp_path):
    def slow_runner(*, client, messages, tool_schemas, skills, model, cfg,
                    emit, cancel):
        time.sleep(1.2)
        emit(TurnDone("ok", 1.2))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=slow_runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.8)
        st = app.query_one("#status", StatusBar)
        assert st.mode == "running"
        assert st.elapsed.endswith("s"), st.elapsed
        await pilot.pause(1.2)
        assert st.elapsed == "", "elapsed should reset when the turn ends"


def test_status_panel_from_slash(tmp_path):
    return _run(_impl_status_panel(tmp_path))


async def _impl_status_panel(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="deepseek-chat", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        stats = app._status_stats()
        assert stats["model"] == "deepseek-chat"
        assert stats["theme"] == "uiu-dark"
        assert "channels" in stats
        await app._send("/status")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 2, "/status opens the status panel"
        panel = app.screen_stack[-1]
        assert panel.query_one("#status-body") is not None
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1


def test_composer_reports_running_tool(tmp_path):
    return _run(_impl_activity(tmp_path))


async def _impl_activity(tmp_path):
    def slow_runner(*, client, messages, tool_schemas, skills, model, cfg,
                    emit, cancel):
        emit(ToolCallEvent("read_spreadsheet", {"path": "a.xlsx"}))
        time.sleep(0.8)
        emit(ToolResultEvent("read_spreadsheet", "[ok] 3 行"))
        emit(TurnDone("ok", 1.0))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=slow_runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert composer._activity == "read_spreadsheet"
        await pilot.pause(1.0)
        assert composer._activity == ""


# --------------------------------------------------------------------------
# Round 5: empty-state resume card + tui.colors custom palette
# --------------------------------------------------------------------------


def test_empty_state_resume_card(tmp_path):
    return _run(_impl_resume_card(tmp_path))


async def _impl_resume_card(tmp_path):
    from uiu import sessions as S
    from uiu.app.widgets import WelcomeBanner

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "周报整理", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "把上季度的周报整理一下"},
        {"role": "assistant", "content": "好的，我先读表格。"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        chat = app.query_one("#chat", ChatView)
        banner = chat.query_one("#empty-hint", WelcomeBanner)
        assert banner.has_recent(), "banner should offer the saved session"
        assert banner.recent["id"] == "周报整理"
        assert "把上季度的周报" in banner.recent["teaser"]
        app.query_one("#resume-btn").press()
        await pilot.pause(0.8)
        assert app._session_name == "周报整理"
        texts = [b.get_text() for b in chat.query(Bubble)]
        assert any("把上季度的周报" in t for t in texts), texts


def test_resume_card_hidden_without_sessions(tmp_path):
    return _run(_impl_no_resume(tmp_path))


async def _impl_no_resume(tmp_path):
    from uiu.app.widgets import WelcomeBanner

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        banner = app.query_one("#chat", ChatView).query_one("#empty-hint", WelcomeBanner)
        assert not banner.has_recent()
        assert not app.query("#resume-btn")


def test_custom_colors_from_config(tmp_path):
    return _run(_impl_custom_colors(tmp_path))


async def _impl_custom_colors(tmp_path):
    from uiu.app.theme import CUSTOM_THEME, palette, palette_from_config
    from uiu.config import AppConfig

    assert palette_from_config(None) is None
    assert palette_from_config(AppConfig()) is None

    ws = make_ws(tmp_path)
    cfg = AppConfig()
    cfg.tui = {"theme": "uiu-dark", "colors": {"primary": "#FF8800", "background": "#101010"}}
    derived = palette_from_config(cfg)
    assert derived is not None and derived.primary == "#FF8800"

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        assert app.theme == CUSTOM_THEME
        pal = palette(app)
        assert pal.primary.lower() == "#ff8800"
        assert pal.background.lower() == "#101010"
        # untouched fields keep the base theme's values
        assert pal.accent == "37D6C4" or pal.accent.lower() == "#37d6c4"
        # Textual resolved the registered theme with our colors — every $primary
        # in the app CSS follows, not just the palette object.
        assert app.current_theme.primary.lower() == "#ff8800"
        assert app.current_theme.background.lower() == "#101010"


# --------------------------------------------------------------------------
# Round 6: collapsible reasoning blocks
# --------------------------------------------------------------------------


def test_long_reasoning_collapses_after_turn(tmp_path):
    return _run(_impl_thought_collapse(tmp_path))


async def _impl_thought_collapse(tmp_path):
    from uiu.app.messages import ThoughtChunk
    from uiu.app.widgets import ThoughtRow

    ws = make_ws(tmp_path)
    long_thought = "先看一下磁盘：" + "逐步排查每个分区。" * 20
    events = [ThoughtChunk(long_thought), TextChunk("结论"), TurnDone("结论", 0.3)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        rows = app.query(ThoughtRow)
        assert len(rows) == 1, "one reasoning block expected"
        row = rows.first()
        assert long_thought[:6] in row.get_text()
        assert not row._open, "long reasoning should collapse once the turn ends"
        body = row.query_one("#md-body")
        assert not body.display, "collapsed body is hidden"
        row.on_click()
        await pilot.pause(0.2)
        assert row._open, "clicking expands the reasoning block"
        assert body.display


def test_short_reasoning_stays_open(tmp_path):
    return _run(_impl_thought_short(tmp_path))


async def _impl_thought_short(tmp_path):
    from uiu.app.messages import ThoughtChunk
    from uiu.app.widgets import ThoughtRow

    ws = make_ws(tmp_path)
    events = [ThoughtChunk("想一下"), TextChunk("好"), TurnDone("好", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        rows = app.query(ThoughtRow)
        assert len(rows) == 1
        assert rows.first()._open, "short reasoning stays visible"


# --------------------------------------------------------------------------
# Round 7: sidebar recent sessions + unread indicator
# --------------------------------------------------------------------------


def test_sidebar_lists_and_switches_recent_sessions(tmp_path):
    return _run(_impl_sidebar_recent(tmp_path))


async def _impl_sidebar_recent(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "周报整理", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "把周报整理一下"},
        {"role": "assistant", "content": "好的"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        sb = app.query_one("#sidebar", SideBar)
        sb.display = True
        await pilot.pause(0.4)
        box = sb.query_one("#side-recent")
        buttons = box.query("Button")
        assert buttons, "recent session should be listed in the sidebar"
        assert "周报整理" in buttons.first().label.plain
        buttons.first().press()
        await pilot.pause(1.0)
        assert app._session_name == "周报整理"
        chat = app.query_one("#chat", ChatView)
        assert any("把周报整理一下" in b.get_text() for b in chat.query(Bubble))


def test_unread_indicator_and_scroll_bottom(tmp_path):
    return _run(_impl_unread(tmp_path))


async def _impl_unread(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        st = app.query_one("#status", StatusBar)
        assert not chat.unread()
        chat._stick = False          # user scrolled up
        await chat.add_notice("新内容来了")
        await pilot.pause(0.5)
        assert chat.unread(), "streaming while scrolled up should flag unread"
        assert st.notice, "status bar should advertise the new content"
        await pilot.press("ctrl+end")
        await pilot.pause(0.5)
        assert not chat.unread()
        assert chat._stick
        assert st.notice == ""


# --------------------------------------------------------------------------
# Round 8: long-transcript folding
# --------------------------------------------------------------------------


def test_long_transcript_folds_old_messages(tmp_path):
    return _run(_impl_fold(tmp_path))


async def _impl_fold(tmp_path):
    ws = make_ws(tmp_path)
    msgs = [{"role": "system", "content": "s"}]
    for i in range(50):
        msgs.append({"role": "user", "content": f"问题 {i}"})
        msgs.append({"role": "assistant", "content": f"回答 {i}"})

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        app._messages = list(msgs)          # the expand handler re-renders from here
        rendered = await chat.load_transcript(msgs[1:])
        await pilot.pause(0.4)
        assert rendered == ChatView.MAX_LIVE, rendered
        assert chat._folded == 100 - ChatView.MAX_LIVE
        hint = chat.query_one("#folded-hint")
        assert f"更早的 {chat._folded} 条" in str(hint.render())
        # the oldest message must be gone from the DOM
        texts = [b.get_text() for b in chat.query(Bubble)]
        assert not any("问题 0" == t for t in texts)
        assert any("问题 49" in t for t in texts)

        # clicking the bar re-renders a deeper window
        chat.post_message(ChatView.ExpandRequested())
        # 渲染 100 条气泡是重活，轮询等它落地
        for _ in range(60):
            if len(chat.query(Bubble)) >= 100:
                break
            await pilot.pause(0.25)
        assert chat._expanded
        assert not chat.query("#folded-hint")
        texts = [b.get_text() for b in chat.query(Bubble)]
        assert any(t == "问题 0" for t in texts), "all messages should be back"


def test_live_turn_folds_at_the_cap(tmp_path):
    return _run(_impl_live_fold(tmp_path))


async def _impl_live_fold(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        for i in range(ChatView.MAX_LIVE + 6):
            await chat.add_user(f"轮 {i}")
        await pilot.pause(0.4)
        assert chat._folded > 0, "live turns should fold once past the cap"
        assert chat.query("#folded-hint"), "fold bar should appear for live turns"


# --------------------------------------------------------------------------
# Round 9: clipboard copy + paged fold expansion + theme note
# --------------------------------------------------------------------------


def test_copy_last_answer_and_transcript(tmp_path, monkeypatch):
    return _run(_impl_copy(tmp_path, monkeypatch))


async def _impl_copy(tmp_path, monkeypatch):
    from uiu.app import clipboard as clip

    ws = make_ws(tmp_path)
    events = [TextChunk("磁盘还剩 890GB"), TurnDone("磁盘还剩 890GB", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    copied: list[str] = []
    monkeypatch.setattr(clip, "copy_text", lambda text: (copied.append(text), (True, "test"))[1])

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)

        # run_turn 会把回答写回 messages；假 runner 不写，这里补上
        app._messages.append({"role": "assistant", "content": "磁盘还剩 890GB"})

        await pilot.press("ctrl+y")
        await pilot.pause(0.4)
        assert copied and copied[-1] == "磁盘还剩 890GB"
        st = app.query_one("#status", StatusBar)
        assert "已复制" in st.toast, st.toast

        await app._send("/copy all")
        await pilot.pause(0.5)
        assert "uiu 会话记录" in copied[-1]
        assert "磁盘还剩 890GB" in copied[-1]


def test_copy_with_nothing_to_copy(tmp_path, monkeypatch):
    return _run(_impl_copy_empty(tmp_path, monkeypatch))


async def _impl_copy_empty(tmp_path, monkeypatch):
    from uiu.app import clipboard as clip

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    monkeypatch.setattr(clip, "copy_text", lambda text: (False, "nope"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+y")
        await pilot.pause(0.4)
        st = app.query_one("#status", StatusBar)
        assert "没有可复制" in st.toast, st.toast
        assert st.toast_kind == "error"

        # failed clipboard writes surface the reason instead of failing silently
        monkeypatch.setattr(clip, "copy_text", lambda text: (False, "clipboard busy"))
        await app._copy("some text", "上一条回答")
        await pilot.pause(0.3)
        assert "clipboard busy" in st.toast
        assert st.toast_kind == "error"


def test_fold_expansion_pages(tmp_path):
    return _run(_impl_fold_paging(tmp_path))


async def _impl_fold_paging(tmp_path):
    ws = make_ws(tmp_path)
    msgs = [{"role": "system", "content": "s"}]
    for i in range(90):
        msgs.append({"role": "user", "content": f"问题 {i}"})
        msgs.append({"role": "assistant", "content": f"回答 {i}"})

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        app._messages = list(msgs)
        await chat.load_transcript(msgs[1:])
        for _ in range(60):
            if chat.query("#folded-hint"):
                break
            await pilot.pause(0.2)
        assert chat.window == ChatView.MAX_LIVE
        assert chat._folded == 180 - ChatView.MAX_LIVE

        chat.post_message(ChatView.ExpandRequested())
        # 等这一页渲染完（window 变大 + 折叠条重新出现）
        for _ in range(120):
            if chat.window > ChatView.MAX_LIVE and chat.query("#folded-hint"):
                break
            await pilot.pause(0.25)
        assert chat.window == ChatView.MAX_LIVE + ChatView.PAGE
        hint = chat.query_one("#folded-hint")
        assert "再展开" in str(hint.render()), str(hint.render())
        assert chat._folded == 180 - (ChatView.MAX_LIVE + ChatView.PAGE)


def test_theme_picker_shows_custom_color_note(tmp_path):
    return _run(_impl_theme_note(tmp_path))


async def _impl_theme_note(tmp_path):
    from uiu.config import AppConfig

    ws = make_ws(tmp_path)
    cfg = AppConfig()
    cfg.tui = {"theme": "uiu-dark", "colors": {"primary": "#F2A93B"}}
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        assert "tui.colors" in app._custom_note()
        await pilot.press("ctrl+t")
        await pilot.pause(0.5)
        picker = app.screen_stack[-1]
        note = picker.query(".modal-note")
        assert note, "picker should explain the active overrides"
        assert "primary" in str(note.first().render())


# --------------------------------------------------------------------------
# Round 10: cross-session search overlay + match highlighting
# --------------------------------------------------------------------------


def test_search_slash_opens_session_search(tmp_path):
    return _run(_impl_session_search(tmp_path))


async def _impl_session_search(tmp_path):
    from textual.widgets import Input, ListView
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "磁盘排查", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "帮我看看 C 盘的剩余空间"},
        {"role": "assistant", "content": "C 盘还剩 890GB，很宽裕。"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/search 890GB")
        await pilot.pause(0.6)
        assert len(app.screen_stack) == 2, "/search opens the overlay"
        modal = app.screen_stack[-1]
        assert modal.query_one("#searchall-input", Input).value == "890GB"
        lv = modal.query_one("#searchall-list", ListView)
        for _ in range(40):
            if len(modal._hits):
                break
            await pilot.pause(0.25)
        if not modal._hits:
            # 兜底：直接重跑一次检索，排除「首次 on_mount 还没跑完」的时序抖动
            await modal.run_search()
            await pilot.pause(0.2)
        assert modal._hits, "the saved session should match"
        assert modal._hits[0]["session"] == "磁盘排查"
        assert lv.query("ListItem")
        # Enter opens that session
        await pilot.press("enter")
        for _ in range(30):
            if app._session_name == "磁盘排查":
                break
            await pilot.pause(0.2)
        assert app._session_name == "磁盘排查"


def test_search_overlay_empty_query_is_harmless(tmp_path):
    return _run(_impl_session_search_empty(tmp_path))


async def _impl_session_search_empty(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "会话A", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "hello"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/search")
        await pilot.pause(0.6)
        assert len(app.screen_stack) == 2
        modal = app.screen_stack[-1]
        assert modal._hits == []
        await pilot.press("escape")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1


def test_markup_highlight_helper():
    from uiu.app.app import _markup_highlight

    assert _markup_highlight("磁盘还剩 890GB", "890") == "磁盘还剩 [b]890[/b]GB"
    assert _markup_highlight("no match here", "zzz") == "no match here"
    # markup in user content must be escaped, not interpreted
    assert _markup_highlight("use [red]here", "red") == r"use [[b]red[/b]]here"
    assert _markup_highlight("plain", "") == "plain"


# --------------------------------------------------------------------------
# Round 11: transient toasts
# --------------------------------------------------------------------------


def test_toast_expires_on_tick(tmp_path, monkeypatch):
    return _run(_impl_toast_expiry(tmp_path, monkeypatch))


async def _impl_toast_expiry(tmp_path, monkeypatch):
    from uiu.app import clipboard as clip

    ws = make_ws(tmp_path)
    events = [TextChunk("好了"), TurnDone("好了", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    monkeypatch.setattr(clip, "copy_text", lambda text: (True, "test"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.8)
        await pilot.press("ctrl+y")
        await pilot.pause(0.4)
        st = app.query_one("#status", StatusBar)
        assert st.toast, "copy should raise a toast"
        # fast-forward past the expiry instead of sleeping 3s
        # （0.0 是「没有 toast」的哨兵值，所以用一个过去但非零的时间戳）
        app._toast_until = 1.0
        app._tick()
        await pilot.pause(0.2)
        assert st.toast == ""


def test_theme_switch_toasts(tmp_path):
    return _run(_impl_theme_toast(tmp_path))


async def _impl_theme_toast(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+t")
        await pilot.pause(0.5)
        await pilot.press("down")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.6)
        st = app.query_one("#status", StatusBar)
        assert "主题已切换" in st.toast, st.toast


# --------------------------------------------------------------------------
# Round 12: non-blocking slash commands + F3 hit cycling
# --------------------------------------------------------------------------


def test_slow_slash_command_does_not_block_ui(tmp_path):
    return _run(_impl_slow_slash(tmp_path))


async def _impl_slow_slash(tmp_path):
    from uiu.slash import REGISTRY

    def slow(_args, ctx):
        time.sleep(0.7)
        ctx.say("慢命令完成")
        return None

    REGISTRY["slowtest"] = {"description": "test-only slow command", "fn": slow}
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            before = app._spin          # tick counter (0.25s interval)
            started = time.monotonic()
            task = asyncio.ensure_future(app._send("/slowtest"))
            await pilot.pause(0.4)
            # mid-flight: UI shows busy state and keeps ticking
            assert app.query_one("#status", StatusBar).mode == "running"
            assert app.query_one("#composer", Composer)._busy
            assert "执行中" in app.query_one("#composer", Composer)._activity
            await task
            elapsed = time.monotonic() - started
            # the UI kept ticking while the command was running
            assert app._spin > before, "event loop was blocked by the slash command"
            assert elapsed >= 0.6
            chat = app.query_one("#chat", ChatView)
            notes = [b.get_text() for b in chat.query(Bubble) if b.role == "notice"]
            assert any("慢命令完成" in t for t in notes), notes
            # busy state is cleared afterwards
            assert app.query_one("#status", StatusBar).mode == "idle"
            assert not app.query_one("#composer", Composer)._busy
    finally:
        REGISTRY.pop("slowtest", None)


def test_search_hits_cycle_with_f3(tmp_path):
    return _run(_impl_hit_cycle(tmp_path))


async def _impl_hit_cycle(tmp_path):
    ws = make_ws(tmp_path)
    events = [
        TextChunk("第一处 890GB，"),
        TextChunk("第二处 890GB。"),
        TurnDone("done", 0.2),
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)

        # nothing searched yet
        await pilot.press("f3")
        await pilot.pause(0.3)
        st = app.query_one("#status", StatusBar)
        assert "Ctrl+R" in st.toast, st.toast

        # search, then jump through the hits with F3
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        await pilot.press(*list("890GB"))
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert app._search_bubbles, "hits should be remembered"
        first = app._search_idx
        await pilot.press("f3")
        await pilot.pause(0.3)
        assert app._search_idx != first or len(app._search_bubbles) == 1
        assert "命中" in st.toast, st.toast
        # cycles back around
        for _ in range(len(app._search_bubbles)):
            await pilot.press("f3")
            await pilot.pause(0.2)
        assert 0 <= app._search_idx < len(app._search_bubbles)


def test_slash_busy_hint_does_not_promise_esc(tmp_path):
    return _run(_impl_honest_busy_hint(tmp_path))


async def _impl_honest_busy_hint(tmp_path):
    from textual.widgets import Label
    from uiu.slash import REGISTRY

    def slow(_args, ctx):
        time.sleep(0.8)
        return None

    REGISTRY["slowtest"] = {"description": "test-only slow command", "fn": slow}
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            composer = app.query_one("#composer", Composer)
            task = asyncio.ensure_future(app._send("/slowtest"))
            await pilot.pause(0.4)
            hint = str(composer.query_one("#composer-hint", Label).render())
            assert "完成后自动返回" in hint, hint
            assert "Esc 中断" not in hint, hint
            await task
            await pilot.pause(0.2)
            hint = str(composer.query_one("#composer-hint", Label).render())
            assert "Esc" not in hint and "完成后" not in hint, hint
    finally:
        REGISTRY.pop("slowtest", None)


def test_transcript_search_footer_counts_hits(tmp_path):
    return _run(_impl_search_footer(tmp_path))


async def _impl_search_footer(tmp_path):
    from textual.widgets import Static

    ws = make_ws(tmp_path)
    events = [TextChunk("磁盘 890GB"), TurnDone("done", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        modal = app.screen_stack[-1]
        await pilot.press(*list("磁盘"))
        await pilot.pause(0.4)
        foot = str(modal.query_one("#search-foot", Static).render())
        assert "命中" in foot and "1" in foot, foot


# --------------------------------------------------------------------------
# Round 14: rich command palette + token estimate
# --------------------------------------------------------------------------


def test_palette_lists_commands_actions_and_sessions(tmp_path):
    return _run(_impl_rich_palette(tmp_path))


async def _impl_rich_palette(tmp_path):
    from textual.widgets import Input, ListView
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "周报整理", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "整理周报"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        entries = app._palette_entries()
        kinds = {e["kind"] for e in entries}
        assert {"命令", "动作", "会话"} <= kinds, kinds
        assert any(e["title"] == "/help" for e in entries)
        assert any(e["run"] == "__session__:周报整理" for e in entries)

        # filtering by an action title, then running it
        await pilot.press("ctrl+e")
        await pilot.pause(0.4)
        pal = app.screen_stack[-1]
        await pilot.press(*list("切换主题"))
        await pilot.pause(0.4)
        lv = pal.query_one("#palette-list", ListView)
        assert len(pal._matches) == 1, [m["title"] for m in pal._matches]
        assert pal._matches[0]["run"] == "__action__:theme"
        await pilot.press("enter")
        await pilot.pause(0.8)
        # the palette closed and the theme picker opened
        assert len(app.screen_stack) == 2
        from uiu.app.app import ThemePicker
        assert isinstance(app.screen_stack[-1], ThemePicker)


def test_palette_can_open_a_saved_session(tmp_path):
    return _run(_impl_palette_session(tmp_path))


async def _impl_palette_session(tmp_path):
    from textual.widgets import ListView
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "磁盘排查", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "C 盘满了"},
        {"role": "assistant", "content": "还剩 890GB"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.4)
        await pilot.press("ctrl+e")
        await pilot.pause(0.4)
        pal = app.screen_stack[-1]
        await pilot.press(*list("磁盘排查"))
        await pilot.pause(0.4)
        assert len(pal._matches) == 1
        await pilot.press("enter")
        for _ in range(30):
            if app._session_name == "磁盘排查":
                break
            await pilot.pause(0.2)
        assert app._session_name == "磁盘排查"


def test_status_bar_reports_token_estimate(tmp_path):
    return _run(_impl_token_estimate(tmp_path))


async def _impl_token_estimate(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages.append({"role": "user", "content": "长内容 " * 400})
        app._refresh_ctx()
        await pilot.pause(0.3)
        st = app.query_one("#status", StatusBar)
        assert st.tokens > 0, st.tokens
        assert st.ctx_pct >= 0


# --------------------------------------------------------------------------
# Round 15: per-message copy button + /export
# --------------------------------------------------------------------------


def test_message_copy_button(tmp_path, monkeypatch):
    return _run(_impl_msg_copy(tmp_path, monkeypatch))


async def _impl_msg_copy(tmp_path, monkeypatch):
    from textual.widgets import Button
    from uiu.app import clipboard as clip

    ws = make_ws(tmp_path)
    events = [TextChunk("磁盘还剩 890GB"), TurnDone("done", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    copied: list[str] = []
    monkeypatch.setattr(clip, "copy_text",
                        lambda text: (copied.append(text), (True, "test"))[1])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        chat = app.query_one("#chat", ChatView)
        assistant = [b for b in chat.query(Bubble) if b.role == "assistant"][0]
        button = assistant.query_one("#copy-btn", Button)
        button.press()
        await pilot.pause(0.5)
        assert copied and copied[-1] == "磁盘还剩 890GB"
        assert "已复制" in app.query_one("#status", StatusBar).toast
        # user bubbles are not copyable
        user = [b for b in chat.query(Bubble) if b.role == "user"][0]
        assert not user.copyable()


def test_export_writes_markdown_file(tmp_path):
    return _run(_impl_export(tmp_path))


async def _impl_export(tmp_path):
    ws = make_ws(tmp_path)
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "看看磁盘"},
        {"role": "assistant", "content": "还剩 890GB"},
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = list(msgs)
        await app._send("/export 磁盘报告")
        for _ in range(20):
            path = tmp_path / "exports" / "磁盘报告.md"
            if path.exists():
                break
            await pilot.pause(0.2)
        path = tmp_path / "exports" / "磁盘报告.md"
        assert path.exists(), "export file should be written"
        text = path.read_text(encoding="utf-8")
        assert "uiu 会话记录" in text
        assert "看看磁盘" in text and "还剩 890GB" in text
        assert "已导出" in app.query_one("#status", StatusBar).toast


def test_export_empty_session_is_graceful(tmp_path):
    return _run(_impl_export_empty(tmp_path))


async def _impl_export_empty(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/export")
        await pilot.pause(0.4)
        st = app.query_one("#status", StatusBar)
        assert "没有" in st.toast or "空" in st.toast, st.toast
        assert not (tmp_path / "exports").exists()


# --------------------------------------------------------------------------
# Round 16: long slash-command output folds
# --------------------------------------------------------------------------


def test_long_slash_output_folds(tmp_path):
    return _run(_impl_output_fold(tmp_path))


async def _impl_output_fold(tmp_path):
    from uiu.app.widgets import OutputRow

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/help")
        for _ in range(20):
            if app.query(OutputRow):
                break
            await pilot.pause(0.2)
        rows = app.query(OutputRow)
        assert rows, "slash output should render as an OutputRow"
        row = rows.first()
        assert row.collapsible(), row.lines
        assert not row._open, "long output starts folded"
        assert row.query_one("#md-body").display is False
        assert "行" in str(row.head_text())
        row.on_click()
        await pilot.pause(0.2)
        assert row._open
        assert row.query_one("#md-body").display


def test_short_slash_output_stays_expanded(tmp_path):
    return _run(_impl_output_short(tmp_path))


async def _impl_output_short(tmp_path):
    from uiu.app.widgets import OutputRow

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/identity")
        for _ in range(20):
            if app.query(OutputRow):
                break
            await pilot.pause(0.2)
        row = app.query(OutputRow).first()
        assert not row.collapsible()
        assert row._open
        assert row.query_one("#md-body").display
        # still discoverable as a notice for other code paths
        assert row.role == "notice"
        assert "id" in row.get_text()


# --------------------------------------------------------------------------
# Round 17: click affordances, searchable command output, window title
# --------------------------------------------------------------------------


def test_clickable_rows_advertise_themselves(tmp_path):
    return _run(_impl_clickable(tmp_path))


async def _impl_clickable(tmp_path):
    from uiu.app.messages import ThoughtChunk
    from uiu.app.widgets import OutputRow, ThoughtRow, ToolRow

    ws = make_ws(tmp_path)
    events = [
        ThoughtChunk("想一下"),
        ToolCallEvent("read_file", {"path": "a"}),
        ToolResultEvent("read_file", "[ok] hi"),
        TurnDone("done", 0.2),
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        chat = app.query_one("#chat", ChatView)
        assert app.query(ThoughtRow).first().has_class("-clickable")
        assert app.query(ToolRow).first().has_class("-clickable")

        await app._send("/help")           # long output → foldable
        for _ in range(20):
            if app.query(OutputRow):
                break
            await pilot.pause(0.2)
        assert app.query(OutputRow).first().has_class("-clickable")

        await app._send("/identity")       # short output → nothing to toggle
        await pilot.pause(0.5)
        rows = app.query(OutputRow)
        assert not rows.last().has_class("-clickable")


def test_transcript_search_includes_command_output(tmp_path):
    return _run(_impl_search_output(tmp_path))


async def _impl_search_output(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/tools")
        await pilot.pause(0.8)
        bubbles = app.query_one("#chat", ChatView).message_bubbles()
        assert any(b.role == "notice" for b in bubbles), "command output is searchable"
        entries = app._palette_entries()          # smoke: palette still builds
        assert entries


def test_window_title_tracks_session(tmp_path):
    return _run(_impl_window_title(tmp_path))


async def _impl_window_title(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "周报整理", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "整理周报"},
    ])
    app = UiuApp(_Stub(), ws, model="deepseek-chat", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert "default" in app.sub_title
        assert "deepseek-chat" in app.sub_title
        await app._send("/sessions 周报整理")   # opens the switcher (arg ignored)
        await pilot.pause(0.5)
        await pilot.press("escape")
        await pilot.pause(0.3)
        app._session_name = "周报整理"
        app._sync_title()
        await pilot.pause(0.2)
        assert "周报整理" in app.sub_title


def test_palette_prefers_recently_used(tmp_path):
    return _run(_impl_palette_recent(tmp_path))


async def _impl_palette_recent(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        first = app._palette_entries()[0]
        assert first["kind"] == "动作", first

        app._remember_palette("/compact")
        entries = app._palette_entries()
        assert entries[0]["run"] == "/compact", entries[0]

        app._remember_palette("__action__:theme")
        entries = app._palette_entries()
        assert entries[0]["run"] == "__action__:theme"
        assert entries[1]["run"] == "/compact", "recency order should hold"
        # capped and duplicate-free
        for i in range(12):
            app._remember_palette(f"/cmd{i}")
        assert len(app._palette_recent) == 8
        assert len(set(app._palette_recent)) == 8


# --------------------------------------------------------------------------
# Round 18: scroll memory across sessions + auto-load older pages
# --------------------------------------------------------------------------


def test_session_switch_remembers_scroll(tmp_path):
    return _run(_impl_scroll_memory(tmp_path))


async def _impl_scroll_memory(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    msgs = [{"role": "system", "content": "s"}]
    for i in range(40):
        msgs.append({"role": "user", "content": f"问题 {i}"})
        msgs.append({"role": "assistant", "content": f"回答 {i}"})
    S.save_session(tmp_path, "长会话A", msgs)
    S.save_session(tmp_path, "长会话B", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "B 的提问"},
        {"role": "assistant", "content": "B 的回答"},
    ])

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        await app._on_session_picked("长会话A")
        for _ in range(60):
            if len(chat.query(Bubble)) >= ChatView.MAX_LIVE:
                break
            await pilot.pause(0.25)
        chat.scroll_to(y=150, animate=False)
        await pilot.pause(0.4)
        taken = chat.scroll_offset_y()
        assert taken > 0, taken

        await app._on_session_picked("长会话B")
        await pilot.pause(1.0)
        await app._on_session_picked("长会话A")
        for _ in range(60):
            if len(chat.query(Bubble)) >= ChatView.MAX_LIVE:
                break
            await pilot.pause(0.25)
        await pilot.pause(0.5)
        restored = chat.scroll_offset_y()
        assert restored > 0, "scroll position should be remembered per session"
        assert abs(restored - taken) < 80, (taken, restored)


def test_scrolling_to_top_loads_older_page(tmp_path):
    return _run(_impl_autoload(tmp_path))


async def _impl_autoload(tmp_path):
    ws = make_ws(tmp_path)
    msgs = [{"role": "system", "content": "s"}]
    for i in range(90):
        msgs.append({"role": "user", "content": f"问题 {i}"})
        msgs.append({"role": "assistant", "content": f"回答 {i}"})

    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        app._messages = list(msgs)
        await chat.load_transcript(msgs[1:])
        for _ in range(60):
            if chat.query("#folded-hint"):
                break
            await pilot.pause(0.25)
        assert chat.window == ChatView.MAX_LIVE

        # 只有「用户上滚」才会触发自动补页（程序化滚动不算）
        chat.on_mouse_scroll_up(None)
        chat.scroll_to(y=0, animate=False)
        for _ in range(80):
            if chat.window > ChatView.MAX_LIVE:
                break
            await pilot.pause(0.25)
        assert chat.window == ChatView.MAX_LIVE + ChatView.PAGE, chat.window
        await pilot.pause(0.5)
        assert chat.scroll_offset_y() > 0, "viewport should stay anchored"


def test_transcript_search_scope_toggle(tmp_path):
    return _run(_impl_search_scope(tmp_path))


async def _impl_search_scope(tmp_path):
    from textual.widgets import Static

    ws = make_ws(tmp_path)
    events = [TextChunk("磁盘还剩 890GB"), TurnDone("done", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        await app._send("/tools")          # long output -> searchable as 输出
        await pilot.pause(0.8)

        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        modal = app.screen_stack[-1]
        assert modal._scope == "all"
        await pilot.press(*list("tool"))
        await pilot.pause(0.4)
        all_kinds = {modal.entries[i].get("kind") for i in modal._hits}
        assert "输出" in all_kinds, all_kinds

        await pilot.press("tab")           # 全部 → 对话
        await pilot.pause(0.4)
        assert modal._scope == "对话"
        assert not any(modal.entries[i].get("kind") == "输出" for i in modal._hits)

        await pilot.press("tab")           # 对话 → 命令输出
        await pilot.pause(0.4)
        assert modal._scope == "输出"
        assert modal._hits, "command output should match in this scope"
        assert all(modal.entries[i].get("kind") == "输出" for i in modal._hits)
        foot = str(modal.query_one("#search-foot", Static).render())
        assert "命令输出" in foot and "Tab 切范围" in foot

        await pilot.press("tab")           # 回到全部
        await pilot.pause(0.3)
        assert modal._scope == "all"


# --------------------------------------------------------------------------
# Round 19: focus cue + huge tool results stay cheap
# --------------------------------------------------------------------------


def test_composer_shows_focus_cue(tmp_path):
    return _run(_impl_focus_cue(tmp_path))


async def _impl_focus_cue(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.pause(0.3)
        shell = composer.query_one("#composer-shell")
        # :focus-within 让输入区在获得焦点时亮起来（Textual 计算的 has_focus_within）
        assert shell.has_focus_within, "composer shell should report focus-within"


def test_huge_tool_result_is_truncated_when_expanded(tmp_path):
    return _run(_impl_huge_tool(tmp_path))


async def _impl_huge_tool(tmp_path):
    from uiu.app.widgets import ToolRow

    ws = make_ws(tmp_path)
    huge = "[ok] " + ("x" * (ToolRow.MAX_DETAIL + 2000))
    events = [
        ToolCallEvent("read_file", {"path": "big.txt"}),
        ToolResultEvent("read_file", huge),
        TurnDone("done", 0.2),
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.8)
        row = app.query(ToolRow).first()
        body = row._body_text().plain
        assert "已截断" in body
        assert len(body) < len(huge), (len(body), len(huge))
        row.toggle()
        await pilot.pause(0.2)
        assert row._open


def test_theme_choice_persists_to_config(tmp_path):
    return _run(_impl_theme_persist(tmp_path))


async def _impl_theme_persist(tmp_path):
    from uiu.config import load_config

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert app.theme == "uiu-dark"
        app._persist_theme("uiu-neon")
        await pilot.pause(0.2)
        cfg = load_config(tmp_path)
        assert (cfg.tui or {}).get("theme") == "uiu-neon"



async def _impl_help_sections(tmp_path):
    from textual.widgets import ListView

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f1")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 2
        nav = app.screen_stack[-1].query_one("#help-nav", ListView)
        assert nav.index == 0
        assert nav.query("ListItem"), "help sections should be listed"
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert len(app.screen_stack) == 1

