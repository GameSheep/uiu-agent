"""Edge-case bug sweep for the TUI: odd data, odd timing, odd input.

Each case is a real regression test — the sweep found several crashes and is
kept here so they cannot come back.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

tx = pytest.importorskip("textual")

from uiu.app import UiuApp  # noqa: E402
from uiu.app.messages import (  # noqa: E402
    Interrupted,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
    TurnDone,
    TurnError,
)
from uiu.app.widgets import Bubble, ChatView, Composer, OutputRow, ToolRow  # noqa: E402
from uiu.workspace import Workspace  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def make_ws(tmp_path: Path) -> Workspace:
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        (tmp_path / name).write_text(f"# {name}\ncontent", encoding="utf-8")
    return Workspace(root=tmp_path, soul="soul", identity="id",
                     user="user", memory="mem", skills=[])


class _Stub:
    pass


def _seq_runner(events, delay=0.01):
    def _runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        for ev in events:
            emit(ev)
            time.sleep(delay)
    return _runner


# --------------------------------------------------------------------------
# 1. odd session data
# --------------------------------------------------------------------------


def test_session_with_only_system_message(tmp_path):
    return _run(_impl_only_system(tmp_path))


async def _impl_only_system(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "只有系统提示", [{"role": "system", "content": "you are uiu"}])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._on_session_picked("只有系统提示")
        await pilot.pause(0.6)
        assert app._session_name == "只有系统提示"
        chat = app.query_one("#chat", ChatView)
        assert chat.query("#empty-hint"), "no turns -> welcome state stays"


def test_transcript_with_hostile_content(tmp_path):
    return _run(_impl_hostile(tmp_path))


async def _impl_hostile(tmp_path):
    ws = make_ws(tmp_path)
    bell_esc = chr(7) + chr(27) + "[31m"
    hostile = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "[red]markup[/red] 'code' **bold** " + bell_esc},
        {"role": "tool", "content": "tool output should be skipped"},
        {"role": "assistant", "content": "x" * 5000},
        {"role": "assistant", "content": ""},
        {"role": "assistant", "content": "emoji \U0001F680 中文 混排"},
        {"role": "user", "content": "   "},
    ]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = list(hostile)
        chat = app.query_one("#chat", ChatView)
        await chat.load_transcript(hostile)
        for _ in range(60):
            if len(chat.query(Bubble)) >= 3:
                break
            await pilot.pause(0.2)
        bubbles = chat.message_bubbles()
        assert bubbles, "hostile content still renders"
        assert all(b.role in ("user", "assistant") for b in bubbles)
        assert not any((b.get_text() or "").strip() == "" for b in bubbles)


def test_unknown_roles_and_bad_shapes_do_not_crash(tmp_path):
    return _run(_impl_bad_shapes(tmp_path))


async def _impl_bad_shapes(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        await chat.load_transcript([
            {"role": "user", "content": None},
            {"role": "assistant"},
            {"role": "function", "content": "legacy"},
            {"role": "user", "content": 12345},
        ])
        await pilot.pause(0.4)
        assert chat.query("#empty-hint") or chat.query(Bubble)


# --------------------------------------------------------------------------
# 2. /export hardening
# --------------------------------------------------------------------------


def test_export_sanitises_names(tmp_path):
    return _run(_impl_export_names(tmp_path))


async def _impl_export_names(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        await app._send("/export ../../evil:name?")
        for _ in range(20):
            if list(tmp_path.joinpath("exports").glob("*.md")):
                break
            await pilot.pause(0.2)
        files = list(tmp_path.joinpath("exports").glob("*.md"))
        assert len(files) == 1, files
        assert files[0].parent == tmp_path / "exports"
        assert ".." not in files[0].name and ":" not in files[0].name


def test_export_failure_is_reported(tmp_path):
    return _run(_impl_export_fail(tmp_path))


async def _impl_export_fail(tmp_path):
    ws = make_ws(tmp_path)
    (tmp_path / "exports").write_text("not a directory", encoding="utf-8")
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        await app._send("/export")
        await pilot.pause(0.4)
        from uiu.app.widgets import StatusBar
        st = app.query_one("#status", StatusBar)
        assert "导出失败" in st.toast, st.toast
        assert st.toast_kind == "error"
        assert app.query_one("#composer", Composer) is not None


# --------------------------------------------------------------------------
# 3. odd timing / concurrency
# --------------------------------------------------------------------------


def test_double_submit_runs_one_turn(tmp_path):
    return _run(_impl_double_submit(tmp_path))


async def _impl_double_submit(tmp_path):
    starts: list[float] = []

    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        starts.append(time.monotonic())
        time.sleep(0.6)
        emit(TurnDone("ok", 0.6))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.2)
        await app.on_composer_submitted(Composer.Submitted("y"))
        await pilot.pause(0.9)
        assert len(starts) == 1, starts
        assert sum(1 for m in app._messages if m.get("role") == "user") == 1


def test_new_chat_and_switch_ignored_while_running(tmp_path):
    return _run(_impl_guard_while_running(tmp_path))


async def _impl_guard_while_running(tmp_path):
    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        time.sleep(0.8)
        emit(TurnDone("ok", 0.8))

    ws = make_ws(tmp_path)
    from uiu import sessions as S
    S.save_session(tmp_path, "another", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "elsewhere"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.2)
        await app.action_new_chat()
        await app._on_session_picked("another")
        await pilot.pause(1.2)
        assert app._session_name == "default"
        assert any(m.get("role") == "user" for m in app._messages)


def test_interrupt_then_next_turn(tmp_path):
    return _run(_impl_interrupt_then_send(tmp_path))


async def _impl_interrupt_then_send(tmp_path):
    calls = {"n": 0}

    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        calls["n"] += 1
        for _ in range(30):
            if cancel.is_set():
                emit(Interrupted())
                return
            time.sleep(0.05)
        emit(TurnDone("late", 1.5))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.3)
        await app.on_composer_cancelled(Composer.Cancelled())
        await pilot.pause(0.8)
        assert not app._turn_running
        assert app.query_one("#status").mode == "idle"
        composer.focus_input()
        await pilot.press("y")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert calls["n"] == 2, calls


def test_resize_while_streaming(tmp_path):
    return _run(_impl_resize_streaming(tmp_path))


async def _impl_resize_streaming(tmp_path):
    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        for i in range(20):
            emit(TextChunk(f"块{i} "))
            time.sleep(0.05)
        emit(TurnDone("done", 1.0))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.2)
        for size in ((70, 24), (120, 40), (58, 20), (120, 40)):
            await pilot.resize_terminal(*size)
            await pilot.pause(0.25)
        await pilot.pause(1.2)
        chat = app.query_one("#chat", ChatView)
        text = "".join(b.get_text() for b in chat.query(Bubble) if b.role == "assistant")
        for i in range(20):
            assert f"块{i}" in text, f"lost chunk {i}"


def test_theme_switch_mid_turn(tmp_path):
    return _run(_impl_theme_mid_turn(tmp_path))


async def _impl_theme_mid_turn(tmp_path):
    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        for i in range(10):
            emit(TextChunk(f"t{i}"))
            time.sleep(0.05)
        emit(TurnDone("done", 0.6))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.15)
        app.theme = "uiu-solar"
        await pilot.pause(0.6)
        app.theme = "uiu-dark"
        await pilot.pause(0.8)
        assert app.theme == "uiu-dark"
        assert app.query_one("#status").mode == "idle"


def test_modal_stacking_is_survivable(tmp_path):
    return _run(_impl_modal_stack(tmp_path))


async def _impl_modal_stack(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+e")
        await pilot.pause(0.4)
        depth = len(app.screen_stack)
        await pilot.press("ctrl+t")
        await pilot.pause(0.4)
        assert len(app.screen_stack) >= depth
        for _ in range(6):
            await pilot.press("escape")
            await pilot.pause(0.3)
        assert len(app.screen_stack) == 1
        assert app.query_one("#composer", Composer) is not None


def test_f3_after_session_switch_does_not_crash(tmp_path):
    return _run(_impl_f3_stale(tmp_path))


async def _impl_f3_stale(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "another", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "elsewhere"},
    ])
    events = [TextChunk("磁盘 890GB"), TurnDone("done", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.9)
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert app._search_bubbles
        await app._on_session_picked("another")
        await pilot.pause(0.8)
        await pilot.press("f3")
        await pilot.pause(0.4)
        assert app.query_one("#status").toast is not None


def test_huge_slash_output_folds(tmp_path):
    return _run(_impl_huge_output(tmp_path))


async def _impl_huge_output(tmp_path):
    from uiu.slash import REGISTRY

    def spam(_args, ctx):
        for i in range(4000):
            ctx.say(f"行 {i}")
        return None

    REGISTRY["spamtest"] = {"description": "test-only", "fn": spam}
    try:
        ws = make_ws(tmp_path)
        app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            await app._send("/spamtest")
            await pilot.pause(0.8)
            rows = app.query(OutputRow)
            assert rows, "huge output still renders as one folded row"
            assert rows.first().collapsible()
            assert rows.first().lines >= 4000
    finally:
        REGISTRY.pop("spamtest", None)


def test_many_tool_rows_in_one_turn(tmp_path):
    return _run(_impl_many_tools(tmp_path))


async def _impl_many_tools(tmp_path):
    events = []
    for i in range(25):
        events.append(ToolCallEvent("read_file", {"path": f"f{i}"}))
        events.append(ToolResultEvent("read_file", f"[ok] file {i}"))
    events.append(TurnDone("done", 2.0))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events, delay=0.005))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.5)
        rows = app.query(ToolRow)
        assert len(rows) == 25, len(rows)
        assert all(not r.running for r in rows), "all tool rows settled"
        assert app.query_one("#composer", Composer)._activity == ""



# --------------------------------------------------------------------------
# 4. stale state after transcript changes
# --------------------------------------------------------------------------


def test_search_hits_are_dropped_when_transcript_changes(tmp_path):
    return _run(_impl_stale_hits(tmp_path))


async def _impl_stale_hits(tmp_path):
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "another", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "elsewhere"},
    ])
    events = [TextChunk("磁盘 890GB"), TurnDone("done", 0.1)]
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.9)
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert app._search_bubbles
        await app._on_session_picked("another")
        await pilot.pause(0.8)
        # the old hit list must not survive the rebuild
        assert not app._search_bubbles, "stale search hits cleared on switch"
        await pilot.press("f3")
        await pilot.pause(0.3)
        assert "Ctrl+R" in app.query_one("#status").toast


def test_search_hits_cleared_on_new_chat(tmp_path):
    return _run(_impl_hits_new_chat(tmp_path))


async def _impl_hits_new_chat(tmp_path):
    events = [TextChunk("磁盘 890GB"), TurnDone("done", 0.1)]
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.9)
        await pilot.press("ctrl+r")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await pilot.pause(0.4)
        await app.action_new_chat()
        await pilot.pause(0.6)
        assert not app._search_bubbles


def test_copy_all_on_empty_session(tmp_path):
    return _run(_impl_copy_all_empty(tmp_path))


async def _impl_copy_all_empty(tmp_path, monkeypatch=None):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = [{"role": "system", "content": "s"}]
        await app._send("/copy all")
        await pilot.pause(0.4)
        st = app.query_one("#status")
        assert "没有可复制" in st.toast, st.toast


# --------------------------------------------------------------------------
# 5. composer edge cases
# --------------------------------------------------------------------------


def test_history_recall_of_slash_does_not_open_menu(tmp_path):
    return _run(_impl_history_slash(tmp_path))


async def _impl_history_slash(tmp_path):
    events = [TurnDone("ok", 0.1)]
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press(*list("/status"))
        await pilot.pause(0.2)
        # dismiss the completion menu without sending
        await pilot.press("escape")
        await pilot.pause(0.2)
        composer.set_history(["/status"])
        await pilot.press("up")
        await pilot.pause(0.3)
        assert composer._input.text == "/status"
        assert not composer._menu.is_visible_menu(), "recall must not pop the menu"


def test_slash_menu_hides_for_unknown_command(tmp_path):
    return _run(_impl_unknown_slash(tmp_path))


async def _impl_unknown_slash(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press(*list("/zzz"))
        await pilot.pause(0.3)
        assert not composer._menu.is_visible_menu()
        await pilot.press("enter")
        await pilot.pause(0.6)
        chat = app.query_one("#chat", ChatView)
        notes = [b.get_text() for b in chat.query(Bubble) if b.role == "notice"]
        assert any("未知命令" in t for t in notes), notes


def test_paste_collapse_survives_editing(tmp_path):
    return _run(_impl_paste_edit(tmp_path))


async def _impl_paste_edit(tmp_path):
    from textual import events

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        area = composer._input
        big = "\n".join(f"line {i}" for i in range(30))
        await area._on_paste(events.Paste(big))
        await pilot.pause(0.3)
        assert area.paste_count() == 1
        area.insert("追问：", maintain_selection_offset=True)
        await pilot.pause(0.2)
        expanded = area.expanded_text()
        assert "追问：" in expanded and big.strip() in expanded


# --------------------------------------------------------------------------
# 6. misc state edges
# --------------------------------------------------------------------------


def test_fold_bar_click_at_cap_is_a_noop(tmp_path):
    return _run(_impl_fold_at_cap(tmp_path))


async def _impl_fold_at_cap(tmp_path):
    ws = make_ws(tmp_path)
    # 直接摆出「已到上限」的状态：避免为了测试渲染 400 条气泡
    msgs = [{"role": "system", "content": "s"}]
    for i in range(60):
        msgs.append({"role": "user", "content": f"问题 {i}"})
        msgs.append({"role": "assistant", "content": f"回答 {i}"})
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one("#chat", ChatView)
        app._messages = list(msgs)
        await chat.load_transcript(msgs[1:], cap=ChatView.MAX_LIVE)
        for _ in range(60):
            if chat.query("#folded-hint"):
                break
            await pilot.pause(0.2)
        chat.window = ChatView.MAX_RENDER
        chat._folded = 100
        await chat._update_fold_hint()
        await pilot.pause(0.2)
        hint = str(chat.query_one("#folded-hint").render())
        assert "上限" in hint, hint
        assert "点击展开" not in hint, hint
        chat.post_message(ChatView.ExpandRequested())
        await pilot.pause(0.5)
        assert chat.window == ChatView.MAX_RENDER, "no further growth past the cap"


def test_double_ctrl_r_unwinds(tmp_path):
    return _run(_impl_double_search(tmp_path))


async def _impl_double_search(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+r")
        await pilot.pause(0.4)
        await pilot.press("ctrl+r")
        await pilot.pause(0.4)
        for _ in range(5):
            await pilot.press("escape")
            await pilot.pause(0.3)
        assert len(app.screen_stack) == 1
        assert app.query_one("#composer", Composer) is not None


def test_sidebar_button_ids_are_unique_with_many_sessions(tmp_path):
    return _run(_impl_many_sessions(tmp_path))


async def _impl_many_sessions(tmp_path):
    from uiu import sessions as S
    from uiu.app.widgets import SideBar

    ws = make_ws(tmp_path)
    for i in range(40):
        S.save_session(tmp_path, f"会话-{i}", [
            {"role": "system", "content": "s"},
            {"role": "user", "content": f"内容 {i}"},
        ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.5)
        sb = app.query_one("#sidebar", SideBar)
        sb.display = True
        await pilot.pause(0.6)
        ids = [w.id for w in sb.query("Button")]
        assert len(ids) == len(set(ids)), "duplicate button ids would crash Textual"
        recent = sb.query_one("#side-recent").query("Button")
        assert 0 < len(recent) <= 4


def test_parallel_tools_with_same_name(tmp_path):
    return _run(_impl_parallel_same_name(tmp_path))


async def _impl_parallel_same_name(tmp_path):
    events = [
        ToolCallEvent("read_file", {"path": "a"}),
        ToolCallEvent("read_file", {"path": "b"}),
        ToolResultEvent("read_file", "[ok] a"),
        ToolResultEvent("read_file", "[ok] b"),
        TurnDone("done", 0.4),
    ]
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events, delay=0.02))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        rows = app.query(ToolRow)
        assert len(rows) == 2, len(rows)
        assert all(not r.running for r in rows)
        assert not app._pending_rows, "pending bookkeeping drained"


def test_tool_result_none_is_safe(tmp_path):
    return _run(_impl_none_result(tmp_path))


async def _impl_none_result(tmp_path):
    events = [
        ToolCallEvent("read_file", {"path": "a"}),
        ToolResultEvent("read_file", None),
        TurnDone("done", 0.2),
    ]
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None,
                 turn_runner=_seq_runner(events))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.9)
        rows = app.query(ToolRow)
        assert len(rows) == 1 and not rows.first().running


# --------------------------------------------------------------------------
# 7. handler lifecycle
# --------------------------------------------------------------------------


def test_clarify_and_confirm_handlers_are_released_on_exit(tmp_path):
    return _run(_impl_handler_lifecycle(tmp_path))


async def _impl_handler_lifecycle(tmp_path):
    from uiu import clarify, confirm

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        assert clarify.get_ask_handler() is not None, "app must install the clarify handler"
        assert confirm.get_confirm_handler() is not None
    # 退出后必须摘掉，否则后续（或另一个）进程里 clarify 会一直阻塞等一个不存在的 UI
    assert clarify.get_ask_handler() is None
    assert confirm.get_confirm_handler() is None


def test_clarify_round_trip(tmp_path):
    return _run(_impl_clarify_roundtrip(tmp_path))


async def _impl_clarify_roundtrip(tmp_path):
    from uiu import clarify

    answered: list[str] = []

    def fake_turn(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        handler = clarify.get_ask_handler()
        answered.append(handler("要继续吗？", ["yes", "no"]) if handler else "<no handler>")
        emit(TurnDone("done", 0.2))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=fake_turn)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        for _ in range(20):
            if len(app.screen_stack) > 1:
                break
            await pilot.pause(0.2)
        assert len(app.screen_stack) == 2, "clarify must open a modal"
        await pilot.press("1")            # 选 yes
        for _ in range(20):
            if len(app.screen_stack) == 1:
                break
            await pilot.pause(0.2)
        await pilot.pause(0.4)
        assert answered and answered[0] == "yes", answered


# --------------------------------------------------------------------------
# 8. slash corner cases
# --------------------------------------------------------------------------


def test_sessions_with_args_is_not_intercepted(tmp_path):
    return _run(_impl_sessions_args(tmp_path))


async def _impl_sessions_args(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await app._send("/sessions rm nope")
        await pilot.pause(0.6)
        assert len(app.screen_stack) == 1, "带有参数的 /sessions 走 slash 而不是浮层"
        chat = app.query_one("#chat", ChatView)
        assert chat.query(Bubble), "命令输出应该落在消息区"


def test_palette_with_no_matches_closes_cleanly(tmp_path):
    return _run(_impl_palette_no_match(tmp_path))


async def _impl_palette_no_match(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+e")
        await pilot.pause(0.4)
        await pilot.press(*list("zzzznope"))
        await pilot.pause(0.4)
        pal = app.screen_stack[-1]
        assert pal._matches == []
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert len(app.screen_stack) == 1
        assert app.query_one("#status") is not None


# --------------------------------------------------------------------------
# 9. session switcher behaviours
# --------------------------------------------------------------------------


def test_session_switcher_deletes_but_not_current(tmp_path):
    return _run(_impl_switcher_delete(tmp_path))


async def _impl_switcher_delete(tmp_path):
    from textual.widgets import ListView
    from uiu import sessions as S

    ws = make_ws(tmp_path)
    S.save_session(tmp_path, "doomed", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "x"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+x")
        await pilot.pause(0.5)
        modal = app.screen_stack[-1]
        lv = modal.query_one("#session-list", ListView)
        ids = [s["id"] for s in modal._sessions]
        assert "doomed" in ids
        lv.index = ids.index("doomed")
        await pilot.press("d")
        await pilot.pause(0.5)
        assert "doomed" not in [s["id"] for s in modal._sessions], "d should delete"
        assert not S.load_session(tmp_path, "doomed")

        # 当前会话不给删
        if "default" in [s["id"] for s in modal._sessions]:
            lv = modal.query_one("#session-list", ListView)
            lv.index = [s["id"] for s in modal._sessions].index("default")
            await pilot.press("d")
            await pilot.pause(0.4)
            assert "default" in [s["id"] for s in modal._sessions]
        await pilot.press("escape")
        await pilot.pause(0.3)


def test_session_switcher_empty_is_graceful(tmp_path):
    return _run(_impl_switcher_empty(tmp_path))


async def _impl_switcher_empty(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("ctrl+x")
        await pilot.pause(0.5)
        modal = app.screen_stack[-1]
        assert modal._sessions == []
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert len(app.screen_stack) == 1
        assert app.query_one("#composer", Composer) is not None


# --------------------------------------------------------------------------
# 10. turn errors
# --------------------------------------------------------------------------


def test_turn_error_shows_hint_and_recovers(tmp_path):
    return _run(_impl_turn_error(tmp_path))


async def _impl_turn_error(tmp_path):
    calls = {"n": 0}

    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        calls["n"] += 1
        if calls["n"] == 1:
            emit(TurnError(RuntimeError("401 invalid_api_key")))
        else:
            emit(TextChunk("恢复了"))
            emit(TurnDone("恢复了", 0.2))

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(1.0)
        chat = app.query_one("#chat", ChatView)
        errs = [b.get_text() for b in chat.query(Bubble) if b.role == "error"]
        assert errs and "API key" in errs[0], errs
        assert app.query_one("#status").mode == "error"
        assert not app._turn_running

        composer.focus_input()
        await pilot.press("y")
        await pilot.press("enter")
        await pilot.pause(1.0)
        assert app.query_one("#status").mode == "idle"
        assert calls["n"] == 2


# --------------------------------------------------------------------------
# 11. layout extremes + sidebar intent
# --------------------------------------------------------------------------


def test_tiny_terminal_does_not_break(tmp_path):
    return _run(_impl_tiny(tmp_path))


async def _impl_tiny(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        for size in ((40, 12), (30, 10), (24, 8), (120, 40)):
            await pilot.resize_terminal(*size)
            await pilot.pause(0.3)
            assert app.query_one("#header") is not None
            assert app.query_one("#composer", Composer) is not None
            assert app.query_one("#status") is not None


def test_sidebar_toggle_wins_over_auto_hide(tmp_path):
    return _run(_impl_sidebar_intent(tmp_path))


async def _impl_sidebar_intent(tmp_path):
    from uiu.app.widgets import SideBar

    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause(0.4)
        sb = app.query_one("#sidebar", SideBar)
        assert not sb.display, "narrow terminal auto-hides the sidebar"
        await pilot.press("ctrl+s")
        await pilot.pause(0.3)
        assert sb.display, "explicit toggle must win"
        assert not app._sidebar_auto_hidden
        await pilot.resize_terminal(120, 40)
        await pilot.pause(0.4)
        assert sb.display


# --------------------------------------------------------------------------
# 12. silent drops must give feedback
# --------------------------------------------------------------------------


def test_dropped_actions_explain_themselves(tmp_path):
    return _run(_impl_dropped_feedback(tmp_path))


async def _impl_dropped_feedback(tmp_path):
    def runner(*, client, messages, tool_schemas, skills, model, cfg, emit, cancel):
        time.sleep(0.9)
        emit(TurnDone("ok", 0.9))

    ws = make_ws(tmp_path)
    from uiu import sessions as S
    S.save_session(tmp_path, "another", [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "elsewhere"},
    ])
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None, turn_runner=runner)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        st = app.query_one("#status")
        composer = app.query_one("#composer", Composer)
        composer.focus_input()
        await pilot.press("x")
        await pilot.press("enter")
        await pilot.pause(0.25)

        await app._send("第二条消息")
        await pilot.pause(0.2)
        assert "正在回复" in st.toast, st.toast
        assert st.toast_kind == "error"

        await app._on_session_picked("another")
        await pilot.pause(0.2)
        assert "切会话" in st.toast, st.toast

        await app.action_new_chat()
        await pilot.pause(0.2)
        assert "新会话" in st.toast, st.toast

        await pilot.pause(1.2)
        assert app._session_name == "default"
        assert sum(1 for m in app._messages if m.get("role") == "user") == 1


# --------------------------------------------------------------------------
# 13. remaining data edges
# --------------------------------------------------------------------------


def test_export_with_all_unsafe_name_falls_back(tmp_path):
    return _run(_impl_export_unsafe(tmp_path))


async def _impl_export_unsafe(tmp_path):
    ws = make_ws(tmp_path)
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        app._messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        await app._send("/export ///???")
        for _ in range(20):
            if list(tmp_path.joinpath("exports").glob("*.md")):
                break
            await pilot.pause(0.2)
        files = list(tmp_path.joinpath("exports").glob("*.md"))
        assert len(files) == 1
        assert files[0].name == "session.md", files[0].name


def test_corrupt_session_does_not_break_the_banner(tmp_path):
    return _run(_impl_corrupt_banner(tmp_path))


async def _impl_corrupt_banner(tmp_path):
    ws = make_ws(tmp_path)
    sdir = tmp_path / "sessions"
    sdir.mkdir(exist_ok=True)
    (sdir / "broken.json").write_text("{not json", encoding="utf-8")
    app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.5)
        # 坏文件不能让首屏/侧栏构建失败
        assert app.query_one("#chat", ChatView) is not None
        assert app._recent_session() == {} or isinstance(app._recent_session(), dict)
        from uiu.app.widgets import WelcomeBanner
        assert app.query_one("#chat", ChatView).query_one("#empty-hint", WelcomeBanner)
