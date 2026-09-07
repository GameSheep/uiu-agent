"""Tests for risk guardrails and action sandboxing (Claude Code / Open Interpreter pattern)."""

from uiu.risk_guardrails import RiskLevel, evaluate_tool_risk, intercept_tool_call


def test_evaluate_tool_risk_blocked_commands():
    # Destructive disk / system commands must be BLOCKED
    r1, _ = evaluate_tool_risk("shell_exec", {"command": "format d: /q"})
    assert r1 == RiskLevel.BLOCKED

    r2, _ = evaluate_tool_risk("shell_exec", {"command": "rmdir /s /q c:\\"})
    assert r2 == RiskLevel.BLOCKED

    r3, _ = evaluate_tool_risk("shell_exec", {"command": "shutdown /s /t 0"})
    assert r3 == RiskLevel.BLOCKED


def test_evaluate_tool_risk_blocked_credentials_and_system():
    # Sensitive credential targets must be BLOCKED
    r1, _ = evaluate_tool_risk("read_file", {"path": "workspace/.env"})
    assert r1 == RiskLevel.BLOCKED

    r2, _ = evaluate_tool_risk("read_file", {"path": "/home/user/.ssh/id_rsa"})
    assert r2 == RiskLevel.BLOCKED

    # Critical system processes must be BLOCKED
    r3, _ = evaluate_tool_risk("proc_kill", {"name": "csrss.exe"})
    assert r3 == RiskLevel.BLOCKED

    r4, _ = evaluate_tool_risk("proc_kill", {"name": "lsass.exe"})
    assert r4 == RiskLevel.BLOCKED


def test_evaluate_tool_risk_confirm_required():
    # External communications or state-modifying actions must require confirmation
    r1, _ = evaluate_tool_risk("send_wechat", {"contact": "张三", "message": "你好"})
    assert r1 == RiskLevel.CONFIRM_REQUIRED

    r2, _ = evaluate_tool_risk("write_file", {"path": "notes/todo.txt", "content": "hello"})
    assert r2 == RiskLevel.CONFIRM_REQUIRED

    r3, _ = evaluate_tool_risk("shell_exec", {"command": "git push --force origin main"})
    assert r3 == RiskLevel.CONFIRM_REQUIRED


def test_evaluate_tool_risk_safe():
    # Read-only and non-destructive operations are SAFE
    r1, _ = evaluate_tool_risk("screen_ocr_find", {"target_text": "确定"})
    assert r1 == RiskLevel.SAFE

    r2, _ = evaluate_tool_risk("window_list", {})
    assert r2 == RiskLevel.SAFE

    r3, _ = evaluate_tool_risk("shell_exec", {"command": "echo 123"})
    assert r3 == RiskLevel.SAFE


def test_intercept_tool_call_blocked():
    allowed, msg = intercept_tool_call("shell_exec", {"command": "format c:"})
    assert allowed is False
    assert "[blocked]" in msg


def test_intercept_tool_call_confirm_flow():
    # User confirms -> allowed
    handler_yes = lambda name, prompt: "yes"
    allowed, _ = intercept_tool_call("send_wechat", {"contact": "李四", "message": "ok"}, confirm_handler=handler_yes)
    assert allowed is True

    # User rejects -> blocked/cancelled
    handler_no = lambda name, prompt: "no"
    allowed, msg = intercept_tool_call("send_wechat", {"contact": "李四", "message": "ok"}, confirm_handler=handler_no)
    assert allowed is False
    assert "[cancelled]" in msg
