"""conversation 成熟度回归：流式tool_calls / 历史修复 / 重试 / 压缩 / 名字 / 时间."""

from types import SimpleNamespace


class _SDelta:
    def __init__(self, content=None, calls=None):
        self.content = content
        self.tool_calls = calls


class _SChoice:
    def __init__(self, delta):
        self.delta = delta


class _SChunk:
    def __init__(self, delta):
        self.choices = [_SChoice(delta)]


class _STC:
    """Streamed tool-call delta fragment."""

    def __init__(self, index, cid=None, name=None, args=None):
        self.index = index
        self.id = cid
        self.function = SimpleNamespace(name=name, arguments=args)


def _chunks_for(item):
    """Script item -> chunk iterator. Items: ("text", s) | ("tools", [(id,name,args)])."""
    kind = item[0]
    if kind == "text":
        s = item[1]
        yield _SChunk(_SDelta(content=s[: len(s) // 2 or None]))
        yield _SChunk(_SDelta(content=s[len(s) // 2:]))
    elif kind == "tools":
        for i, (cid, name, args) in enumerate(item[1]):
            yield _SChunk(_SDelta(calls=[_STC(i, cid=cid, name=name)]))
            yield _SChunk(_SDelta(calls=[_STC(i, args=args[: len(args) // 2])]))
            yield _SChunk(_SDelta(calls=[_STC(i, args=args[len(args) // 2:])]))


class _Completions:
    def __init__(self, script):
        self.script = list(script)
        self.seen_messages = []

    def create(self, **kw):
        self.seen_messages.append(kw.get("messages"))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        assert kw.get("stream") is True, "run_turn must stream"
        return _chunks_for(item)


class _Chat:
    def __init__(self, script):
        self.completions = _Completions(script)


class _Client:
    def __init__(self, script):
        self.chat = _Chat(script)


def test_tool_calls_preserved_in_history():
    import uiu.agent as A
    orig_execute = A.tools.execute
    A.tools.execute = lambda *a, **k: "工具结果"
    try:
        client = _Client([
            ("tools", [("c1", "read_file", '{"path":"a"}')]),
            ("text", "搞定"),
        ])
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "读a"}]
        texts = []
        out = A.run_turn(client, messages, [], model="m", on_text=texts.append)
        assert out == "搞定"
        assert "".join(texts) == "搞定"  # 流式到达
        second = client.chat.completions.seen_messages[1]
        asst = [m for m in second if m.get("role") == "assistant"][0]
        assert asst.get("tool_calls") and asst["tool_calls"][0]["id"] == "c1"
        assert asst["tool_calls"][0]["function"] == {"name": "read_file", "arguments": '{"path":"a"}'}
        assert any(m.get("role") == "tool" and m.get("tool_call_id") == "c1" for m in second)
    finally:
        A.tools.execute = orig_execute


def test_repair_drops_orphan_tool():
    from uiu.agent import repair_tool_sequence
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "ghost", "content": "x"},
        {"role": "assistant", "content": "ok"},
    ]
    out = repair_tool_sequence(msgs)
    assert not any(m.get("role") == "tool" for m in out)


def test_repair_demotes_assistant_without_results():
    from uiu.agent import repair_tool_sequence
    msgs = [
        {"role": "assistant", "content": "想调工具",
         "tool_calls": [{"id": "c9", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "user", "content": "换个话题"},
    ]
    out = repair_tool_sequence(msgs)
    assert out[0].get("content") == "想调工具" and "tool_calls" not in out[0]


def test_repair_keeps_valid_chain():
    from uiu.agent import repair_tool_sequence
    msgs = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "r"},
    ]
    assert repair_tool_sequence(msgs) == msgs


def test_transient_retry_then_success(monkeypatch):
    import uiu.agent as A
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    notices = []
    client = _Client([TimeoutError("timed out"), TimeoutError("timed out"), ("text", "好了")])
    messages = [{"role": "user", "content": "hi"}]
    out = A.run_turn(client, messages, [], model="m",
                     on_notice=notices.append)
    assert out == "好了" and sleeps == [2, 4] and len(notices) == 2


def test_non_transient_raises_immediately(monkeypatch):
    import uiu.agent as A
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    try:
        A.run_turn(_Client([ValueError("bad key")]), [{"role": "user", "content": "hi"}], [], model="m")
    except ValueError:
        pass
    else:
        raise AssertionError("should raise")
    assert sleeps == []


def test_context_overflow_compacts_and_retries():
    import uiu.agent as A
    notices = []
    big = [{"role": "system", "content": "sys"}]
    for i in range(10):
        big.append({"role": "user", "content": f"q{i} " * 5000})
        big.append({"role": "assistant", "content": f"a{i} " * 5000})
    client = _Client([RuntimeError("maximum context length exceeded"), ("text", "瘦身后回答")])
    out = A.run_turn(client, big, [], model="m", on_notice=notices.append)
    assert out == "瘦身后回答"
    assert any("压缩" in n for n in notices)
    assert len(big) < 21


def test_agent_name_from_identity(tmp_path):
    from uiu.workspace import Workspace
    assert Workspace(root=tmp_path, identity="# IDENTITY — 小刃\n").agent_name() == "小刃"
    assert Workspace(root=tmp_path, identity="## 名字\n阿月\n").agent_name() == "阿月"
    assert Workspace(root=tmp_path, identity="").agent_name() == "agent"


def test_resolve_agent_name_priority(tmp_path):
    from uiu.config import AppConfig, resolve_agent_name
    from uiu.workspace import Workspace
    ws = Workspace(root=tmp_path, identity="## 名字\n小刃\n")
    assert resolve_agent_name(AppConfig(), ws) == "小刃"
    cfg = AppConfig(agent_name="大黄")
    assert resolve_agent_name(cfg, ws) == "大黄"
    assert resolve_agent_name(None, None) == "agent"


def test_config_agent_name_cli(tmp_path):
    import argparse
    from uiu.commands import cmd_config
    ns = argparse.Namespace(workspace=str(tmp_path), api_key=None, set_secret=None,
                            unset_secret=None, list=False, show_values=False,
                            agent_name="铁蛋")
    assert cmd_config(ns) == 0
    from uiu.config import load_config
    assert load_config(tmp_path).agent_name == "铁蛋"


def test_get_time_format():
    from uiu.system_tools import get_time
    out = get_time()
    assert "周" in out and len(out) > 16


def test_tool_groups_cover_registry():
    from uiu.tools import BUILTIN_TOOLS, tool_groups
    grouped = [n for _, names in tool_groups() for n in names]
    assert set(grouped) == set(BUILTIN_TOOLS)
    labels = [l for l, _ in tool_groups()]
    assert "base" in labels and "browser" in labels


def test_banner_builds_ascii_only(tmp_path):
    from uiu.tui import build_banner
    from uiu.workspace import Workspace
    ws = Workspace(root=tmp_path, identity="## 名字\n小刃\n")
    out = build_banner(ws, "m", [{"function": {"name": "x"}}], False)
    assert "小刃" in out and "Available Tools" in out
    out.encode("gbk")  # GBK 安全：管道/旧终端不崩


def test_status_shows_config_name(tmp_path):
    from uiu.slash import SlashContext, dispatch
    from uiu.config import AppConfig
    from uiu.workspace import Workspace
    say = []
    ctx = SlashContext(ws=Workspace(root=tmp_path, identity="## 名字\n小刃\n"),
                       cfg=AppConfig(agent_name="大兵"), say=say.append, tool_schemas=[])
    dispatch("/status", ctx)
    assert "agent: 大兵" in say[0]


def test_banner_renders_in_panel(tmp_path):
    import io
    from rich.console import Console
    from rich.panel import Panel
    from uiu.tui import build_banner
    from uiu.workspace import Workspace
    ws = Workspace(root=tmp_path, identity="## 名字\n小刃\n")
    text = build_banner(ws, "m", [], False)
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=100).print(Panel(text, border_style="green"))
    out = buf.getvalue()
    assert "Available Tools" in out and "小刃" in out
