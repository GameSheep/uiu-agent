"""Slash registry: shared by TUI + gateway (no LLM)."""

from types import SimpleNamespace


def _ctx(tmp_path):
    from uiu.slash import SlashContext
    ws = SimpleNamespace(
        root=tmp_path / "ws",
        skills=[],
        identity="ID",
        system_prompt=lambda: "SYS",
    )
    (tmp_path / "ws").mkdir(parents=True, exist_ok=True)
    say = []
    return SlashContext(ws=ws, say=say.append, tool_schemas=[]), say


def test_help_lists_commands(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    handled, quit_sig = dispatch("/help", ctx)
    assert handled and quit_sig is None
    assert any("/cron" in line for line in say)


def test_unknown_command(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    handled, _ = dispatch("/nope", ctx)
    assert handled and "未知命令" in say[0]


def test_non_slash_not_handled(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    handled, _ = dispatch("hello", ctx)
    assert handled is False and say == []


def test_memory_and_save_resume(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    ctx.messages = [{"role": "system", "content": "SYS"}]
    dispatch("/memory 喜欢短回答", ctx)
    assert "喜欢短回答" in (ctx.ws.root / "MEMORY.md").read_text(encoding="utf-8")
    dispatch("/save t1", ctx)
    ctx.messages.clear()
    dispatch("/resume t1", ctx)
    assert ctx.messages and ctx.messages[0]["content"] == "SYS"
    dispatch("/sessions", ctx)
    assert any("t1" in line for line in say)


def test_quit_signal(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    for cmd in ("/quit", "/exit"):
        handled, quit_sig = dispatch(cmd, ctx)
        assert handled and quit_sig == "__quit__"


def test_cron_list_empty(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    dispatch("/cron", ctx)
    assert "no cron jobs" in say[0]


def test_status_and_usage(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    ctx.messages = [{"role": "system", "content": "SYS"},
                    {"role": "user", "content": "hi"}]
    ctx.cfg = __import__("types").SimpleNamespace(default="m")
    ctx.tool_schemas = [{"function": {"name": "x", "description": ""}}]
    dispatch("/status", ctx)
    assert "model: m" in say[0] and "tools: 1" in say[0]
    dispatch("/usage", ctx)
    assert "tok" in say[1]


def test_new_resets_with_snapshot(tmp_path):
    from uiu.slash import dispatch
    ctx, say = _ctx(tmp_path)
    ctx.messages = [{"role": "system", "content": "SYS"},
                    {"role": "user", "content": "hi"}]
    dispatch("/new", ctx)
    assert ctx.messages == [{"role": "system", "content": "SYS"}]
    assert "新会话" in say[0]


def test_toolbar_html():
    from uiu.tui import _RunState, _toolbar_html
    st = _RunState()
    out = _toolbar_html(st, "m", [{"role": "user", "content": "hi"}], 60, 2)
    assert "idle" in out and "ctx:" in out and "tools:60" in out
    st.mode = "running"
    assert "running" in _toolbar_html(st, "m", [], 0, 0)
