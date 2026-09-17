"""CLI 输出约定：进度反馈 + --json（审计 §1.4 / §4.3）。

契约：--json 时 **stdout 只有一个 JSON 文档**（进度/提示走 stderr），退出码语义不变；
长任务要能看到「在做什么、花了多久」。
"""

from __future__ import annotations

import json

import pytest

from uiu import cli_io, sessions as S
from uiu.main import main


def _ws(tmp_path, n=0):
    ws = tmp_path / "ws"
    for i in range(n):
        S.save_session(ws, f"s{i}", [{"role": "user", "content": "x" * 100}])
    return ws


def _only_json(capsys) -> dict:
    """断言 stdout 恰好是一个 JSON 文档，并返回它。"""
    out = capsys.readouterr().out
    assert out.strip(), "stdout 不该为空"
    payload = json.loads(out)          # 多一个字符都会解析失败
    assert isinstance(payload, dict) and "ok" in payload and "command" in payload
    return payload


def test_sessions_usage_json_envelope(tmp_path, capsys):
    ws = _ws(tmp_path, 3)
    assert main(["--json", "--workspace", str(ws), "sessions", "usage"]) == 0
    payload = _only_json(capsys)
    assert payload["ok"] is True
    assert payload["command"] == "sessions.usage"
    assert payload["data"]["count"] == 3
    assert "largest" in payload["data"]


def test_sessions_list_json_envelope(tmp_path, capsys):
    ws = _ws(tmp_path, 2)
    assert main(["--json", "--workspace", str(ws), "sessions", "list"]) == 0
    payload = _only_json(capsys)
    ids = [s["id"] for s in payload["data"]["sessions"]]
    assert sorted(ids) == ["s0", "s1"]
    assert all("bytes" in s for s in payload["data"]["sessions"])


def test_json_flag_also_works_after_the_subcommand(tmp_path, capsys):
    ws = _ws(tmp_path, 1)
    assert main(["--workspace", str(ws), "sessions", "usage", "--json"]) == 0
    assert _only_json(capsys)["command"] == "sessions.usage"


def test_error_path_keeps_exit_code_and_reports_in_json(tmp_path, capsys):
    ws = _ws(tmp_path)
    rc = main(["--json", "--workspace", str(ws), "trash", "--restore", "ghost"])
    assert rc == 2, "退出码语义不变"
    payload = _only_json(capsys)
    assert payload["ok"] is False
    assert "没有" in payload["error"]


def test_doctor_json_keeps_stdout_clean(tmp_path, capsys):
    from uiu.config import ensure_workspace

    ws = _ws(tmp_path)
    ensure_workspace(ws)
    rc = main(["--json", "--workspace", str(ws), "doctor", "--lint"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)          # stdout 只有 JSON
    assert payload["command"] == "doctor"
    assert payload["data"]["exit_code"] == rc
    assert payload["data"]["findings"], "findings 应当在 data 里"
    assert "[error]" in captured.err or "[info]" in captured.err, "人读输出应在 stderr"


def test_audit_json_envelope(tmp_path, capsys):
    from uiu import audit

    ws = _ws(tmp_path)
    audit.record(ws, "tool_call", tool="read_file", status="ok", ms=3)
    assert main(["--json", "--workspace", str(ws), "audit", "--tail", "5"]) == 0
    payload = _only_json(capsys)
    assert payload["data"]["events"][0]["tool"] == "read_file"


def test_backup_json_envelope(tmp_path, capsys):
    ws = _ws(tmp_path, 1)
    (ws / "config.yaml").write_text("agent_name: uiu\n", encoding="utf-8")
    assert main(["--json", "--workspace", str(ws), "backup"]) == 0
    payload = _only_json(capsys)
    assert payload["data"]["path"].endswith(".zip")
    assert payload["data"]["bytes"] > 0


def test_sessions_prune_json_requires_yes_to_apply(tmp_path, capsys):
    ws = _ws(tmp_path, 4)
    assert main(["--json", "--workspace", str(ws), "sessions", "prune", "--keep", "1"]) == 0
    payload = _only_json(capsys)
    assert payload["data"]["applied"] is False
    assert len(S.list_sessions(ws)) == 4

    assert main(["--json", "--workspace", str(ws), "sessions", "prune",
                 "--keep", "1", "--yes"]) == 0
    payload = _only_json(capsys)
    assert payload["data"]["applied"] is True
    assert len(S.list_sessions(ws)) == 1


def test_human_mode_is_unchanged(tmp_path, capsys):
    ws = _ws(tmp_path, 2)
    assert main(["--workspace", str(ws), "sessions", "usage"]) == 0
    out = capsys.readouterr().out
    assert "会话数: 2" in out
    assert not out.strip().startswith("{"), "人读模式不该输出 JSON"


def test_no_ansi_or_carriage_return_in_non_tty_output(tmp_path, capsys):
    """非 TTY（管道/CI）下不能混进转义符，否则日志会花。"""
    cli_io.set_json_mode(False)
    with cli_io.step("假装一个长步骤") as s:
        s["detail"] = "ok"
    capsys.readouterr()

    ws = _ws(tmp_path, 2)
    main(["--json", "--workspace", str(ws), "sessions", "usage"])
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err):
        assert "\r" not in stream and "\x1b" not in stream


def test_step_marks_failure(capsys):
    cli_io.set_json_mode(False)
    with pytest.raises(RuntimeError):
        with cli_io.step("会失败的一步"):
            raise RuntimeError("boom")
    out = capsys.readouterr().out
    assert "会失败的一步" in out and "✗" in out
