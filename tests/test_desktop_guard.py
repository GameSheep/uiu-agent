"""Unit tests for Desktop Guard, keyboard/mouse non-interference, and daemon mode."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from uiu.desktop_guard import (
    CONTROLLED_DESKTOP_TOOLS,
    ExecutionContext,
    assert_desktop_allowed,
    check_desktop_action_allowed,
    execution_guard,
    get_current_context,
    get_user_idle_seconds,
)
from uiu.desktop_tools import dispatch_tool
from uiu.tools import call_tool


def test_idle_context_blocks_controlled_desktop_tools():
    """In default IDLE state, all keyboard and mouse operations must be blocked."""
    assert get_current_context() == ExecutionContext.IDLE

    for tool_name in ["mouse_click_at", "type_text", "press_key", "window_focus", "send_wechat"]:
        allowed, reason = check_desktop_action_allowed(tool_name)
        assert not allowed, f"Tool {tool_name} should be blocked in IDLE"
        assert "[blocked]" in reason
        assert "静默后台免干扰拦截" in reason

    with pytest.raises(PermissionError) as exc_info:
        assert_desktop_allowed("mouse_click_at")
    assert "[blocked]" in str(exc_info.value)


def test_idle_context_allows_readonly_tools():
    """Read-only or non-mouse/keyboard tools are not blocked by desktop guard."""
    assert get_current_context() == ExecutionContext.IDLE

    # window_list doesn't move mouse or press keys
    allowed, _ = check_desktop_action_allowed("window_list")
    assert allowed

    allowed, _ = check_desktop_action_allowed("read_file")
    assert allowed

    allowed, _ = check_desktop_action_allowed("shell_exec")
    assert allowed


def test_dispatch_tool_blocked_in_idle():
    """dispatch_tool returns blocked message when called in IDLE."""
    assert get_current_context() == ExecutionContext.IDLE

    res = dispatch_tool("mouse_click_at", {"x": 500, "y": 500})
    assert "[blocked]" in res
    assert "严禁执行 'mouse_click_at' 干扰系统键盘与鼠标" in res

    res = dispatch_tool("type_text", {"text": "hello"})
    assert "[blocked]" in res

    res = dispatch_tool("window_focus", {"title_keyword": "notepad"})
    assert "[blocked]" in res


def test_call_tool_intercepted_in_idle():
    """call_tool via tools.py gets intercepted by risk guardrails in IDLE."""
    assert get_current_context() == ExecutionContext.IDLE

    res = call_tool("mouse_click_at", json.dumps({"x": 100, "y": 100}))
    assert "[error]" in res
    assert "[blocked]" in res


def test_user_dialogue_context_allows_desktop_tools():
    """When user explicitly converses with uiu, desktop operations are allowed."""
    with execution_guard(ExecutionContext.USER_DIALOGUE, source="user:tui"):
        assert get_current_context() == ExecutionContext.USER_DIALOGUE

        allowed, reason = check_desktop_action_allowed("mouse_click_at")
        assert allowed
        assert "用户明确在对话中发起指令" in reason

        allowed, _ = check_desktop_action_allowed("type_text")
        assert allowed

    # Reverts to IDLE immediately after exiting the block
    assert get_current_context() == ExecutionContext.IDLE
    allowed, _ = check_desktop_action_allowed("mouse_click_at")
    assert not allowed


def test_cron_scheduled_run_context():
    """During cron run, desktop tools are allowed only if user is not actively typing/clicking."""
    with execution_guard(ExecutionContext.CRON_SCHEDULED_RUN, source="cron:job_123"):
        assert get_current_context() == ExecutionContext.CRON_SCHEDULED_RUN

        # Case 1: User is idle (e.g. 10 seconds since last keystroke)
        with patch("uiu.desktop_guard.get_user_idle_seconds", return_value=10.0):
            allowed, reason = check_desktop_action_allowed("mouse_click_at")
            assert allowed
            assert "定时任务到点执行且用户处于空闲状态" in reason

        # Case 2: User is actively working (e.g. typed 0.5 seconds ago)
        with patch("uiu.desktop_guard.get_user_idle_seconds", return_value=0.5):
            allowed, reason = check_desktop_action_allowed("mouse_click_at")
            assert not allowed
            assert "[blocked]" in reason
            assert "定时任务避让保护" in reason

    assert get_current_context() == ExecutionContext.IDLE


def test_cron_run_job_sets_cron_context(tmp_path, monkeypatch):
    """Verifies that cron.run_job enters CRON_SCHEDULED_RUN context."""
    from uiu.cron import add_job, run_job

    job = add_job(tmp_path, "test_job", "30m", "echo 123", run_shell=True)

    captured_contexts = []

    from uiu import desktop_guard
    orig_execution_guard = desktop_guard.execution_guard

    def tracking_guard(ctx, source=""):
        captured_contexts.append((ctx, source))
        return orig_execution_guard(ctx, source=source)

    monkeypatch.setattr("uiu.desktop_guard.execution_guard", tracking_guard)

    out = run_job(tmp_path, job)
    assert Path(out).exists()
    assert len(captured_contexts) == 1
    assert captured_contexts[0][0] == ExecutionContext.CRON_SCHEDULED_RUN
    assert "cron:" in captured_contexts[0][1]


def test_daemon_status(tmp_path):
    """Verifies status_daemon query."""
    from uiu.daemon import status_daemon
    status = status_daemon(tmp_path)
    assert "running" in status
    assert "total_jobs" in status
    assert "enabled_jobs" in status
    assert status["total_jobs"] == 0
