"""Tests for Autonomous ReAct Task Agent Loop."""

import json
import pytest
from uiu.autonomous_loop import AutonomousTaskRunner, StepTrace, run_autonomous_goal
from uiu.desktop_tools import dispatch_tool


def test_autonomous_task_runner_custom_planner():
    # Define a 2-step mock planner
    def mock_planner(goal, history, ctx):
        if len(history) == 0:
            return {
                "thought": "检查显示器配置",
                "tool_name": "display_scaling_info",
                "tool_args": {},
            }
        elif len(history) == 1:
            return {
                "thought": "计算目标坐标",
                "tool_name": "coordinate_anti_drift",
                "tool_args": {"box": [10, 20, 100, 40], "strategy": "safe_center"},
                "completed": True,
            }
        return {"completed": True}

    runner = AutonomousTaskRunner(
        max_steps=5,
        enable_macro_recall=False,
        auto_compile_on_success=True,
        planner_fn=mock_planner,
    )

    result = runner.run("测试自主多轮执行与宏沉淀")
    assert result.success is True
    assert len(result.steps) == 2
    assert result.steps[0].tool_name == "display_scaling_info"
    assert result.steps[1].tool_name == "coordinate_anti_drift"
    assert result.steps[0].reflection != ""
    assert result.macro_compiled is not None


def test_autonomous_runner_risk_guardrail_block():
    def evil_planner(goal, history, ctx):
        return {
            "thought": "尝试破坏性操作",
            "tool_name": "run_cmd",
            "tool_args": {"command": "rmdir /s /q C:\\"},
        }

    runner = AutonomousTaskRunner(
        max_steps=3,
        enable_macro_recall=False,
        planner_fn=evil_planner,
    )

    result = runner.run("执行危险指令")
    assert result.success is False
    assert len(result.steps) == 1
    assert "[blocked]" in result.steps[0].observation
    assert "安全风控阻断" in result.steps[0].observation


def test_autonomous_runner_macro_recall(monkeypatch):
    import uiu.autonomous_loop as al

    # Mock episodic memory recall
    monkeypatch.setattr(
        al,
        "find_matching_macro",
        lambda goal: {"macro_name": "mock_recall_macro"},
    )
    monkeypatch.setattr(
        al,
        "run_compiled_macro",
        lambda name, **kwargs: "[ok] mock macro executed in 5ms",
    )

    runner = AutonomousTaskRunner(enable_macro_recall=True)
    res = runner.run("快速打开微信并置顶")

    assert res.success is True
    assert res.macro_compiled == "mock_recall_macro"
    assert len(res.steps) == 1
    assert res.steps[0].tool_name == "macro_fast_run"


def test_desktop_tools_autonomous_goal_dispatch():
    # Dispatch via desktop_tools
    res_str = dispatch_tool(
        "autonomous_goal_run",
        {"goal": "测试自主执行", "max_steps": 2},
    )
    data = json.loads(res_str)
    assert "success" in data
    assert "steps" in data
    assert "summary" in data
