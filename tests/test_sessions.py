"""Sessions: save/load/list/remove/compact (no LLM)."""


def _msgs(n=4):
    out = [{"role": "system", "content": "sys"}]
    for i in range(n):
        out.append({"role": "user", "content": f"q{i} " * 50})
        out.append({"role": "assistant", "content": f"a{i} " * 50})
    return out


def test_save_load_list_remove(tmp_path):
    from uiu import sessions as S
    ws = tmp_path / "ws"
    S.save_session(ws, "s1", _msgs(2))
    S.save_session(ws, "s2", _msgs(1))
    back = S.load_session(ws, "s1")
    assert back and back[0]["role"] == "system"
    assert S.load_session(ws, "nope") is None
    ids = [s["id"] for s in S.list_sessions(ws)]
    assert set(ids) == {"s1", "s2"}
    assert S.remove_session(ws, "s1") is True
    assert S.remove_session(ws, "s1") is False


def test_compact_passthrough_when_small():
    from uiu.sessions import compact_messages
    msgs = _msgs(1)
    assert compact_messages(msgs, max_chars=10**9) is msgs


def test_compact_trims_without_summarizer(tmp_path):
    from uiu.sessions import compact_messages
    msgs = _msgs(6)
    out = compact_messages(msgs, max_chars=100)
    assert out[0]["role"] == "system"
    assert len(out) < len(msgs)


def test_compact_with_summarizer(tmp_path):
    from uiu.sessions import compact_messages
    msgs = _msgs(6)
    out = compact_messages(msgs, max_chars=100, summarizer=lambda old: "摘要：聊了x")
    assert any("摘要" in (m.get("content", "") or "") for m in out)
