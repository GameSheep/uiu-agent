"""Security policy contract (audit §5.2 / §5.3 / §5.6).

- 路径：workspace 白名单放行、越界需确认、凭据目录与系统目录拒绝
- shell：按语义分类——只读放行，写/网络/进程/系统/包管理/解释器需确认，破坏性命令拒绝
- 审计：每次工具执行与每次确认都留 append-only 记录，且密钥字段脱敏
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from uiu import audit
from uiu.risk_guardrails import RiskLevel, classify_command, evaluate_tool_risk
from uiu._sandbox import PathDecision, classify_path


# --------------------------------------------------------------------------
# 路径策略（§5.2）
# --------------------------------------------------------------------------


def test_paths_inside_workspace_are_allowed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "notes" / "a.txt"
    decision, _, resolved = classify_path(str(target), workspace=ws)
    assert decision is PathDecision.ALLOW and resolved == target


def test_temp_dir_is_allowed():
    decision, _, _ = classify_path(str(Path(tempfile.gettempdir()) / "x.txt"))
    assert decision is PathDecision.ALLOW


def test_paths_outside_workspace_need_confirmation(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = Path.home() / "Documents" / "report.docx"
    decision, why, _ = classify_path(str(outside), workspace=ws)
    assert decision is PathDecision.CONFIRM
    assert "workspace 之外" in why


def test_credential_dirs_are_denied(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for path in (Path.home() / ".ssh" / "config",
                 Path.home() / ".aws" / "credentials",
                 Path.home() / ".uiu" / "daemon.log"):
        decision, why, _ = classify_path(str(path), workspace=ws)
        assert decision is PathDecision.DENY, path
        # 凭据目录命中「凭据」；个别文件（credentials）先被敏感文件名规则拦下
        assert ("凭据" in why) or ("敏感文件" in why) or ("不可访问" in why), why


def test_system_and_secret_files_are_denied(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert classify_path(str(ws / ".env"), workspace=ws)[0] is PathDecision.DENY
    assert classify_path(
        str(Path.home() / ".ssh" / "id_rsa"), workspace=ws)[0] is PathDecision.DENY
    assert classify_path(str(ws / "config.yaml"), for_write=True,
                         workspace=ws)[0] is PathDecision.DENY


def test_read_outside_workspace_now_requires_confirmation(tmp_path):
    """以前读任意用户目录是静默放行的，现在必须过用户确认。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = str(Path.home() / "Documents" / "x.txt")
    level, reason = evaluate_tool_risk("read_file", {"path": outside})
    assert level is RiskLevel.CONFIRM_REQUIRED, reason
    assert "workspace 之外" in reason


def test_read_inside_workspace_is_safe(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("UIU_WORKSPACE", str(ws))
    level, _ = evaluate_tool_risk("read_file", {"path": str(ws / "a.txt")})
    assert level is RiskLevel.SAFE


def test_write_inside_workspace_still_confirms(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("UIU_WORKSPACE", str(ws))
    level, reason = evaluate_tool_risk("write_file", {"path": str(ws / "a.txt")})
    assert level is RiskLevel.CONFIRM_REQUIRED
    assert "持久修改" in reason


# --------------------------------------------------------------------------
# shell 语义（§5.3）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [
    "dir C:\\",
    "type report.txt",
    "git status",
    "git diff HEAD",
    "type f.txt | findstr hello",
    "systeminfo",
    "cmd /c dir",
    "echo hello",
])
def test_readonly_commands_are_safe(cmd):
    level, reason = classify_command(cmd)
    assert level is RiskLevel.SAFE, f"{cmd} -> {level}: {reason}"


@pytest.mark.parametrize("cmd", [
    "rm notes.txt",
    "del /q notes.txt",
    "mkdir build",
    "move a.txt b.txt",
    "copy a.txt b.txt",
    "curl https://example.com",
    "wget https://example.com/x.zip",
    "ssh user@host",
    "taskkill /im notepad.exe",
    "reg add HKCU\\Software\\x /v y /d z",
    "pip install requests",
    "python -c \"print(1)\"",
    "powershell -enc SQBFAFgA",
    "cmd /c del notes.txt",
    "echo hi > out.txt",
    "git push origin master",
    "git commit -m x",
    "frobnicate --now",
    "dir && rm notes.txt",
])
def test_side_effecting_commands_require_confirmation(cmd):
    level, reason = classify_command(cmd)
    assert level is RiskLevel.CONFIRM_REQUIRED, f"{cmd} -> {level}: {reason}"


@pytest.mark.parametrize("cmd", [
    "format C:",
    "diskpart",
    "mkfs.ext4 /dev/sda1",
    "shutdown /s /t 0",
    "poweroff",
])
def test_destructive_commands_are_blocked(cmd):
    level, reason = classify_command(cmd)
    assert level is RiskLevel.BLOCKED, f"{cmd} -> {level}: {reason}"


def test_shell_exec_goes_through_the_classifier():
    assert evaluate_tool_risk("shell_exec", {"command": "rm x"})[0] is RiskLevel.CONFIRM_REQUIRED
    assert evaluate_tool_risk("shell_exec", {"command": "dir"})[0] is RiskLevel.SAFE
    assert evaluate_tool_risk("shell_exec", {"command": "format C:"})[0] is RiskLevel.BLOCKED


# --------------------------------------------------------------------------
# 审计日志（§5.6）
# --------------------------------------------------------------------------


def test_record_and_read_events(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path))
    assert audit.record(None, "tool_call", tool="read_file", status="ok", ms=12)
    events = audit.read_events(tmp_path, tail=10)
    assert len(events) == 1
    assert events[0]["tool"] == "read_file"
    assert events[0]["status"] == "ok"
    assert events[0]["time"] and events[0]["ts"]


def test_secrets_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path))
    audit.record(None, "tool_call", tool="x",
                 args={"api_key": "sk-live-123", "path": "a.txt",
                       "nested": {"password": "hunter2", "ok": 1}})
    raw = audit.audit_path(tmp_path).read_text(encoding="utf-8")
    assert "sk-live-123" not in raw and "hunter2" not in raw
    event = audit.read_events(tmp_path)[0]
    assert event["args"]["api_key"] == "***"
    assert event["args"]["nested"]["password"] == "***"
    assert event["args"]["path"] == "a.txt"


def test_audit_rotates_when_large(tmp_path, monkeypatch):
    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(audit, "MAX_BYTES", 200)
    for i in range(8):
        audit.record(None, "tool_call", tool=f"t{i}", status="ok", detail="x" * 60)
    files = sorted(p.name for p in audit.audit_dir(tmp_path).glob("uiu-audit*.jsonl"))
    assert len(files) >= 2, files


def test_every_tool_call_is_audited(tmp_path, monkeypatch):
    from uiu import tools

    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path))
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    out = tools.call_tool("read_file", json.dumps({"path": str(tmp_path / "a.txt")}))
    assert "hello" in out

    events = [e for e in audit.read_events(tmp_path, tail=20) if e["event"] == "tool_call"]
    assert events and events[-1]["tool"] == "read_file"
    assert events[-1]["status"] == "ok"


def test_blocked_and_denied_calls_are_audited(tmp_path, monkeypatch):
    from uiu import tools

    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path))
    blocked = tools.call_tool("shell_exec", json.dumps({"command": "format C:"}))
    assert "[blocked]" in blocked or "error" in blocked

    events = audit.read_events(tmp_path, tail=20)
    kinds = {e["event"] for e in events}
    assert "tool_blocked" in kinds, events

    # 有确认通道且用户拒绝 → 记为 rejected，并且工具不执行
    from uiu import confirm as confirm_mod
    monkeypatch.setattr(confirm_mod, "_confirm", lambda name, prompt: "no")
    cancelled = tools.call_tool("shell_exec", json.dumps({"command": "rm x"}))
    assert "cancelled" in cancelled
    monkeypatch.setattr(confirm_mod, "_confirm", None)

    decisions = [e.get("decision") for e in audit.read_events(tmp_path, tail=20)
                 if e["event"] == "tool_confirm"]
    assert "rejected" in decisions, decisions


def test_confirm_prompt_shows_command_and_cwd(tmp_path, monkeypatch):
    """确认框必须给足信息：完整命令 + cwd（审计 §5.3）。"""
    from uiu import confirm as confirm_mod
    from uiu.risk_guardrails import intercept_tool_call

    seen: list[str] = []
    monkeypatch.setattr(confirm_mod, "_confirm",
                        lambda name, prompt: (seen.append(prompt), "no")[1])
    allowed, reason = intercept_tool_call(
        "shell_exec", {"command": "rm -rf build", "cwd": "C:/proj"},
        confirm_handler=confirm_mod._confirm)
    assert allowed is False and "cancelled" in reason
    assert "rm -rf build" in seen[0]
    assert "C:/proj" in seen[0]
    monkeypatch.setattr(confirm_mod, "_confirm", None)


def test_cli_audit_prints_events(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    ws.mkdir()
    audit.record(ws, "tool_call", tool="read_file", status="ok", ms=5)
    assert main(["--workspace", str(ws), "audit", "--tail", "5"]) == 0
    out = capsys.readouterr().out
    assert "read_file" in out and "ok" in out

    # --json 现在统一走信封（round 14）：stdout 只有一个文档，事件在 data.events 里
    assert main(["--workspace", str(ws), "audit", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "audit"
    assert payload["data"]["events"][0]["tool"] == "read_file"


# --------------------------------------------------------------------------
# 递归强删的危险目标（P1-8 加固：端到端测试真跑出来过的缺口）
# --------------------------------------------------------------------------

_DESTRUCTIVE_CASES = [
    "rm -rf /", "rm -rf ~", "rm -rf /etc", "rm -rf .", "rm -rf ../",
    "rm -rf /var/lib", "sudo rm -rf /usr/local", "rm -rf /boot",
    "rd /s /q C:\\Windows", "rmdir /s C:\\",
    "Remove-Item -Recurse -Force C:\\Windows",
    "Remove-Item -Recurse -Force C:\\Users",
    "ri -r -fo %USERPROFILE%",
    "Remove-Item -Recurse -Force $env:USERPROFILE",
    "del /f /s /q C:\\Users",
    "dd if=/dev/zero of=/dev/sda",
    "vssadmin delete shadows /all",
    "bcdedit /set safeboot minimal",
    "reg delete HKLM\\SOFTWARE\\Foo",
    "chmod -R 777 /",
]

_ALLOWED_CASES = [
    "rm -rf ./build", "rm -rf /tmp/uiu-probe", "rm -rf node_modules",
    "Remove-Item -Recurse -Force .\\dist", "del /q .\\tmp.txt",
    "del /f /s /q .\\build\\*", "git status", "pip install -e .",
]


@pytest.mark.parametrize("cmd", _DESTRUCTIVE_CASES)
def test_destructive_targets_are_blocked(cmd):
    """递归强删只要指向整盘/家目录/系统目录就必须 BLOCKED，而不是「确认一下」。"""
    risk, why = classify_command(cmd)
    assert risk == RiskLevel.BLOCKED, f"{cmd} 被判为 {risk.value}（{why}）"


@pytest.mark.parametrize("cmd", _ALLOWED_CASES)
def test_normal_cleanup_is_not_blocked(cmd):
    """正常开发操作不能被误拦（删自己的 build/临时目录是合理需求）。"""
    risk, _ = classify_command(cmd)
    assert risk != RiskLevel.BLOCKED, f"{cmd} 被误拦成 BLOCKED"


def test_destructive_reason_is_actionable():
    """拦截理由要能说明白是哪种高危，而不是一句笼统的「危险」。"""
    risk, why = classify_command("rm -rf /etc")
    assert risk == RiskLevel.BLOCKED
    assert "系统目录" in why or "不可逆" in why, why
