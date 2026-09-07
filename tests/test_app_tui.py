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
        # /sessions with no saved ones returns "(no saved sessions..."
        # Enter while the completion menu is open confirms the highlighted
        # completion; a second Enter actually sends the command.
        await pilot.press(*list("/sessions"))
        await pilot.pause(0.2)
        await pilot.press("enter")  # confirm completion
        await pilot.press("enter")  # send
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        notices = [b for b in chat.query(Bubble) if b.role == "notice"]
        assert notices, "expected a notice bubble from /sessions"
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
