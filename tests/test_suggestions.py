"""Suggestions (usage-aware) — macro→cron + repeated topic detection."""

from pathlib import Path


def _root(tmp_cwd) -> Path:
    p = tmp_cwd / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_macro(root: Path, name: str, desc: str = "") -> None:
    import json
    from uiu.macro_recorder import macros_dir
    (macros_dir(root) / f"{name}.json").write_text(
        json.dumps({"name": name, "description": desc, "steps": [{"t": "key", "key": "enter"}]},
                   ensure_ascii=False), encoding="utf-8")


def _save_msgs(root: Path, sid: str, texts: list[str]) -> None:
    from uiu.sessions import save_session
    msgs = [{"role": "user", "content": t} for t in texts]
    save_session(root, sid, msgs)


def test_record_and_scan_macro_cron(tmp_cwd):
    from uiu.suggestions import record_macro_play, scan_suggestions
    root = _root(tmp_cwd)
    _make_macro(root, "backup")
    for _ in range(3):
        record_macro_play(root, "backup")
    items = scan_suggestions(root)
    ids = [s["id"] for s in items]
    assert "macro-cron-backup" in ids


def test_macro_below_threshold_no_suggestion(tmp_cwd):
    from uiu.suggestions import record_macro_play, scan_suggestions
    root = _root(tmp_cwd)
    _make_macro(root, "rare")
    record_macro_play(root, "rare")  # 只回放 1 次
    assert scan_suggestions(root) == []


def test_macro_play_records_usage(tmp_cwd, monkeypatch):
    """macro_play 成功后写 usage.json（AI 生成宏闭环）。"""
    from uiu.macro_recorder import macros_dir
    from uiu.desktop_guard import ExecutionContext, execution_guard
    import json
    root = _root(tmp_cwd)
    (macros_dir(root) / "m.json").write_text(json.dumps(
        {"name": "m", "description": "", "steps": [{"t": "key", "key": "enter", "delay_before": 0.1}]},
        ensure_ascii=False), encoding="utf-8")
    from uiu.macros import macro_play
    monkeypatch.setattr("uiu.macro_player.press_key", lambda **k: "[ok]")
    with execution_guard(ExecutionContext.USER_DIALOGUE):
        out = macro_play("m")
    assert "1 步" in out
    usage = json.loads((root / "usage.json").read_text(encoding="utf-8"))
    assert usage["macro_plays"]["m"] == 1


def test_accept_creates_cron_job(tmp_cwd):
    from uiu.suggestions import record_macro_play, accept_suggestion
    from uiu import cron
    root = _root(tmp_cwd)
    _make_macro(root, "daily")
    for _ in range(3):
        record_macro_play(root, "daily")
    out = accept_suggestion(root, "macro-cron-daily")
    assert "[ok]" in out and "每天" in out
    jobs = cron.load_jobs(root)
    assert any(j["name"] == "macro-daily" for j in jobs)
    # 已接受 → 不再建议
    from uiu.suggestions import scan_suggestions
    assert scan_suggestions(root) == []


def test_dismiss_latches(tmp_cwd):
    from uiu.suggestions import record_macro_play, dismiss_suggestion, scan_suggestions
    root = _root(tmp_cwd)
    _make_macro(root, "x")
    for _ in range(3):
        record_macro_play(root, "x")
    assert scan_suggestions(root)
    dismiss_suggestion(root, "macro-cron-x")
    assert scan_suggestions(root) == []


def test_repeated_topic_detected(tmp_cwd):
    from uiu.suggestions import scan_suggestions
    root = _root(tmp_cwd)
    _save_msgs(root, "s1", ["帮我部署服务器", "部署服务器出错了", "怎么部署服务器", "再部署一次"])
    items = scan_suggestions(root)
    topic_ids = [s["id"] for s in items if s["kind"] == "topic"]
    assert any("部署" in tid for tid in topic_ids), topic_ids


def test_stop_words_and_slash_excluded(tmp_cwd):
    from uiu.suggestions import scan_suggestions
    root = _root(tmp_cwd)
    _save_msgs(root, "s1", ["帮我一下", "请帮我", "这个怎么弄", "/skills list"])
    assert scan_suggestions(root) == []


def test_slash_suggestions_roundtrip(tmp_cwd):
    from uiu.suggestions import record_macro_play
    from uiu.slash import SlashContext, dispatch
    from uiu.workspace import Workspace
    root = _root(tmp_cwd)
    _make_macro(root, "rep")
    for _ in range(3):
        record_macro_play(root, "rep")
    said = []
    ctx = SlashContext(ws=Workspace(root=root), say=said.append, tool_schemas=[])
    dispatch("/suggestions", ctx)
    assert "macro-cron-rep" in said[0]
    said.clear()
    dispatch("/suggestions accept macro-cron-rep", ctx)
    assert "[ok]" in said[0]
    said.clear()
    dispatch("/suggestions", ctx)
    assert "暂无建议" in said[0]
