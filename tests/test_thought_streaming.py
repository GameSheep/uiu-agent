"""Unit tests for thought / reasoning streaming across agent.py, ChatView, and UiuApp."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import pytest

from uiu.agent import _call_once_stream, run_turn

tx = pytest.importorskip("textual")
from uiu.app.messages import ThoughtChunk, ToolCallEvent, ToolResultEvent, TextChunk, TurnDone
from uiu.app.widgets.chat_view import ChatView, Bubble


class MockDelta:
    def __init__(self, content=None, reasoning_content=None, tool_calls=None):
        self.content = content
        self.reasoning_content = reasoning_content
        self.tool_calls = tool_calls
        self.model_extra = {}


class MockChoice:
    def __init__(self, delta):
        self.delta = delta


class MockChunk:
    def __init__(self, delta):
        self.choices = [MockChoice(delta)] if delta is not None else []


class MockClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return iter(self._chunks)


def test_call_once_stream_native_reasoning():
    chunks = [
        MockChunk(MockDelta(reasoning_content="分析问题中...")),
        MockChunk(MockDelta(reasoning_content="准备回答：")),
        MockChunk(MockDelta(content="你好！")),
        MockChunk(MockDelta(content="很高兴见到你。")),
    ]
    client = MockClient(chunks)
    thoughts = []
    texts = []

    res = _call_once_stream(
        client=client,
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="deepseek-r1",
        on_text=lambda t: texts.append(t),
        on_thought=lambda t: thoughts.append(t),
    )

    assert "".join(thoughts) == "分析问题中...准备回答："
    assert "".join(texts) == "你好！很高兴见到你。"
    assert res["content"] == "你好！很高兴见到你。"


def test_call_once_stream_think_tag_parsing():
    chunks = [
        MockChunk(MockDelta(content="<think>开始深度思考")),
        MockChunk(MockDelta(content="，规划步骤</think>正式")),
        MockChunk(MockDelta(content="回答内容。")),
    ]
    client = MockClient(chunks)
    thoughts = []
    texts = []

    res = _call_once_stream(
        client=client,
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        model="qwen-coder",
        on_text=lambda t: texts.append(t),
        on_thought=lambda t: thoughts.append(t),
    )

    assert "".join(thoughts) == "开始深度思考，规划步骤"
    assert "".join(texts) == "正式回答内容。"
    assert res["content"] == "<think>开始深度思考，规划步骤</think>正式回答内容。"


def test_run_turn_interleaved_thought_and_tools():
    """Verify thoughts -> tool -> thoughts -> final response sequence."""
    class MultiRoundClient:
        def __init__(self):
            self.round = 0
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kwargs):
            self.round += 1
            if self.round == 1:
                tc = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="get_time", arguments="{}"))
                return iter([
                    MockChunk(MockDelta(reasoning_content="我需要调用时间工具...")),
                    MockChunk(MockDelta(tool_calls=[tc])),
                ])
            else:
                return iter([
                    MockChunk(MockDelta(reasoning_content="时间已返回，生成总结...")),
                    MockChunk(MockDelta(content="当前时间是 09:30。")),
                ])

    client = MultiRoundClient()
    sequence = []

    final = run_turn(
        client=client,
        messages=[{"role": "user", "content": "几点啦"}],
        tool_schemas=[{"type": "function", "function": {"name": "get_time", "parameters": {}}}],
        model="deepseek-r1",
        on_thought=lambda t: sequence.append(("thought", t)),
        on_tool_call=lambda n, a: sequence.append(("tool_call", n)),
        on_tool_result=lambda n, r: sequence.append(("tool_result", n)),
        on_text=lambda t: sequence.append(("text", t)),
    )

    assert final == "当前时间是 09:30。"
    assert ("thought", "我需要调用时间工具...") in sequence
    assert ("tool_call", "get_time") in sequence
    assert ("tool_result", "get_time") in sequence
    assert ("thought", "时间已返回，生成总结...") in sequence
    assert ("text", "当前时间是 09:30。") in sequence


def test_chat_view_thought_lifecycle():
    """Verify ChatView correctly mounts ThoughtBubble, tool notice, and assistant summary."""
    pytest.importorskip("textual")
    from textual.app import App, ComposeResult

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield ChatView("agent")

    async def run():
        app = TestApp()
        async with app.run_test(size=(100, 30)) as pilot:
            cv = app.query_one(ChatView)
            # 1. User message
            await cv.add_user("几点啦")
            # 2. Interleaved thought 1
            await cv.stream_thought("准备")
            await cv.stream_thought("查询当前时间...")
            # 3. Tool executed
            await cv.add_tool("get_time", True, "2026-09-08 09:30:00")
            # 4. Interleaved thought 2
            await cv.stream_thought("时间已拿到，生成回答")
            # 5. Final summary
            await cv.stream("现在是上午 09:30。")
            await cv.finish_assistant()
            await pilot.pause(0.2)

            bubbles = cv.query(Bubble)
            roles = [b.role for b in bubbles]
            assert roles == ["user", "thought", "notice", "thought", "assistant"]
            assert "查询当前时间" in bubbles[1].get_text()
            assert "现在是上午 09:30。" in bubbles[4].get_text()

    asyncio.run(run())
