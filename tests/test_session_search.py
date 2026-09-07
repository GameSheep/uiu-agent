"""Session search (Hermes session_search stdlib edition)."""


def _save(ws, sid, msgs):
    from uiu.sessions import save_session
    save_session(ws, sid, msgs)


def _msgs(turns):
    out = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        out.append({"role": "user", "content": f"用户问题 {i} 部署服务器"})
        out.append({"role": "assistant", "content": f"回答 {i} 用 docker 部署"})
    return out


def test_search_finds_matching_session(tmp_cwd):
    from uiu.sessions import search_sessions
    ws = tmp_cwd / "workspace"
    _save(ws, "s1", _msgs(3))
    _save(ws, "s2", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "今天天气如何"},
        {"role": "assistant", "content": "晴"},
    ])
    hits = search_sessions(ws, "部署")
    assert len(hits) == 1 and hits[0]["session"] == "s1"
    assert hits[0]["text"].startswith("用户问题") or hits[0]["text"].startswith("回答")
    assert hits[0]["context"], "bookend context should be present"


def test_search_all_terms_and_match(tmp_cwd):
    from uiu.sessions import search_sessions
    ws = tmp_cwd / "workspace"
    _save(ws, "a", _msgs(2))
    _save(ws, "b", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "今天聊聊吃饭"},
        {"role": "assistant", "content": "好"},
    ])
    # both terms in one session → only that session matches
    hits = search_sessions(ws, "部署 docker")
    assert len(hits) == 1 and hits[0]["session"] == "a"
    # disjoint terms → no match
    assert search_sessions(ws, "部署 天气") == []


def test_search_empty_and_absent(tmp_cwd):
    from uiu.sessions import search_sessions
    ws = tmp_cwd / "workspace"
    _save(ws, "a", _msgs(1))
    assert search_sessions(ws, "") == []
    assert search_sessions(ws, "不存在的东西") == []


def test_search_limit(tmp_cwd):
    from uiu.sessions import search_sessions
    ws = tmp_cwd / "workspace"
    for i in range(4):
        _save(ws, f"s{i}", _msgs(1))
    assert len(search_sessions(ws, "部署", limit=2)) == 2


def test_search_case_insensitive_ascii(tmp_cwd):
    from uiu.sessions import search_sessions
    ws = tmp_cwd / "workspace"
    _save(ws, "code", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Let's deploy the API server"},
        {"role": "assistant", "content": "done"},
    ])
    hits = search_sessions(ws, "DEPLOY API")
    assert len(hits) == 1


def test_tool_registered_and_callable(tmp_cwd):
    from uiu.tools import BUILTIN_TOOLS, call_tool
    import json
    assert "session_search" in BUILTIN_TOOLS
    ws = tmp_cwd / "workspace"
    _save(ws, "s1", _msgs(1))
    out = call_tool("session_search", json.dumps({"query": "部署"}))
    assert "部署" in out and "s1" in out


def test_cli_sessions_search(tmp_cwd, capsys):
    import argparse
    from uiu.commands import cmd_sessions
    from uiu.sessions import save_session
    ws = tmp_cwd / "workspace"
    save_session(ws, "x1", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "我们讨论过部署策略"},
        {"role": "assistant", "content": "用 k8s"},
    ])
    ns = argparse.Namespace(workspace=str(ws), action="search", query="部署策略", limit=5)
    assert cmd_sessions(ns) == 0
    assert "x1" in capsys.readouterr().out


def test_slash_search(tmp_cwd):
    from uiu.slash import SlashContext, dispatch
    from uiu.workspace import load_workspace
    from uiu.sessions import save_session
    root = tmp_cwd / "workspace"
    save_session(root, "y1", [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "提到过上海出差的安排"},
        {"role": "assistant", "content": "记下了"},
    ])
    said = []
    ctx = SlashContext(ws=load_workspace(root), messages=[], say=said.append)
    dispatch("/search 上海 出差", ctx)
    assert said and "y1" in said[0]
