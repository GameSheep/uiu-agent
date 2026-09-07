"""/compact slash command — truncation fallback + LLM summary with archive + memory flush."""

from types import SimpleNamespace


def _ctx(tmp_cwd, client=None, model="", cfg=None):
    from uiu.slash import SlashContext
    from uiu.workspace import Workspace
    root = tmp_cwd / "workspace"  # == $UIU_WORKSPACE (conftest fixture)
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root=root)
    ctx = SlashContext(ws=ws, client=client, model=model, cfg=cfg, messages=None,
                       tool_schemas=[])
    return ctx, ws


def _long_msgs(n=6, chunk=8000):
    """Big enough to exceed compact_messages' 60k default budget."""
    out = [{"role": "system", "content": "SYS"}]
    for i in range(n):
        out.append({"role": "user", "content": f"第{i}轮问题 " + "x" * chunk})
        out.append({"role": "assistant", "content": f"第{i}轮回答 " + "y" * chunk})
    return out


def test_compact_short_conversation_skips(tmp_cwd):
    from uiu.slash import dispatch
    ctx, ws = _ctx(tmp_cwd)
    ctx.messages = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}]
    say = []
    ctx.say = say.append
    dispatch("/compact", ctx)
    assert "暂无需压缩" in say[0]


def test_compact_truncation_mode_without_client(tmp_cwd):
    from uiu.slash import dispatch
    ctx, ws = _ctx(tmp_cwd)
    ctx.messages = _long_msgs()
    say = []
    ctx.say = say.append
    dispatch("/compact", ctx)
    assert "截断" in say[0]
    assert ctx.messages[0]["role"] == "system"
    assert len(ctx.messages) < len(_long_msgs())


def test_compact_llm_summary_archives_and_flushes(tmp_cwd, monkeypatch):
    """Summarizer returns [MEMORY] block → archived + memory flushed + ctx replaced."""
    from uiu.slash import dispatch
    from uiu import agent as A

    def fake_run_turn(client, messages, tool_schemas, model, cfg, skills, **kw):
        # summarizer 单轮：返回带 [MEMORY] 的摘要
        assert messages[0]["role"] == "user"
        assert "<history>" in messages[0]["content"]
        return "摘要内容 [MEMORY]\n- 用户喜欢极简回答\n- 无\n"

    monkeypatch.setattr(A, "run_turn", fake_run_turn)
    ctx, ws = _ctx(tmp_cwd, client=SimpleNamespace(), model="m")
    ctx.messages = _long_msgs()
    say = []
    ctx.say = say.append
    dispatch("/compact", ctx)
    out = say[0]
    assert "已 LLM 摘要" in out and "auto-compact" in out
    # memory flushed via learning.memory_add (writes to $UIU_WORKSPACE/MEMORY.md)
    mem = (ws.root / "MEMORY.md").read_text(encoding="utf-8")
    assert "用户喜欢极简回答" in mem
    assert "无" not in mem
    # archived snapshot exists
    from uiu.sessions import list_sessions
    ids = [s["id"] for s in list_sessions(ws.root)]
    assert any(i.startswith("auto-compact") for i in ids)


def test_compact_no_client_does_not_archive(tmp_cwd):
    from uiu.slash import dispatch
    ctx, ws = _ctx(tmp_cwd)
    ctx.messages = _long_msgs()
    say = []
    ctx.say = say.append
    dispatch("/compact", ctx)
    from uiu.sessions import list_sessions
    assert list_sessions(ws.root) == []
