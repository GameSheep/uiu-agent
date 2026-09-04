"""Subagent delegation with stubbed LLM loop (no network)."""

from types import SimpleNamespace

import pytest


def _ctx(seen):
    import uiu.agent as agent_mod

    def fake_run_turn(client, messages, tool_schemas, skills=None, model="", cfg=None,
                      on_text=None, on_tool_call=None, on_tool_result=None):
        seen.append({"schemas": [s["function"]["name"] for s in tool_schemas],
                     "msgs": [m.get("content", "")[:40] for m in messages]})
        return "子结论"

    monkey = pytest.MonkeyPatch()
    monkey.setattr(agent_mod, "run_turn", fake_run_turn)
    import uiu.delegation as deleg
    ws = SimpleNamespace(skills=[], system_prompt=lambda: "SYS")
    cfg = SimpleNamespace(default="m", max_tokens=100)
    deleg.set_context("client", cfg, ws,
                      [{"type": "function", "function": {"name": "shell_exec", "description": "", "parameters": {}}},
                       {"type": "function", "function": {"name": "read_file", "description": "", "parameters": {}}}])
    return monkey, deleg


def test_delegate_task_ok():
    seen = []
    monkey, deleg = _ctx(seen)
    try:
        assert deleg.delegate_task("做事") == "子结论"
        assert seen[0]["schemas"] == ["shell_exec", "read_file"]
    finally:
        monkey.undo()


def test_delegate_task_whitelist():
    seen = []
    monkey, deleg = _ctx(seen)
    try:
        deleg.delegate_task("做事", tools=["read_file"])
        assert seen[0]["schemas"] == ["read_file"]
    finally:
        monkey.undo()


def test_delegate_task_validates():
    seen = []
    monkey, deleg = _ctx(seen)
    try:
        assert deleg.delegate_task("").startswith("[error]")
        assert deleg.delegate_task("x" * 20001).startswith("[error]")
    finally:
        monkey.undo()


def test_delegate_batch_order():
    seen = []
    monkey, deleg = _ctx(seen)
    try:
        out = deleg.delegate_batch(["a", "b", "c"])
        assert out.count("子结论") == 3 and "## 任务2" in out
        assert deleg.delegate_batch([]).startswith("[error]")
    finally:
        monkey.undo()


def test_no_context_errors():
    import uiu.delegation as deleg
    deleg._CTX = None
    assert deleg.delegate_task("hi").startswith("[error]")
