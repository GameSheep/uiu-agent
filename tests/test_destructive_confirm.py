"""破坏性操作的确认契约（P0-5 同类）：非交互环境必须失败，不能"没做却报成功"。

实测踩到：uiu restore 在管道/CI 里（stdin 不是 TTY）会走 input() 拿到 EOF，
当成「用户取消」，打印「已取消」并 **返回 0**。于是

    uiu restore backup.zip && echo OK

会打印 OK，而其实什么都没恢复。灾难恢复路径绝不能这样。
现在三态明确：--yes 继续；交互终端里问用户；**非交互又没有 --yes → rc=2 + 说清楚怎么办**。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _seed(ws: Path) -> Path:
    """建一个 workspace：一个会话 + .env，然后做一份备份。返回备份路径。"""
    from uiu import sessions as S
    from uiu.config import ensure_workspace
    from uiu.main import main

    ensure_workspace(ws)
    S.save_session(ws, "important", [{"role": "user", "content": "别弄丢我"}])
    (ws / ".env").write_text("SMOKE_TOKEN=abc123\\n", encoding="utf-8")
    assert main(["--workspace", str(ws), "backup"]) == 0
    return sorted((ws / "backups").glob("*.zip"))[-1]


def test_restore_without_yes_in_a_pipe_fails_loudly(tmp_path, capsys, monkeypatch):
    """非交互 + 没有 --yes：必须 rc=2 且什么都不改（以前是 rc=0 静默不做）。"""
    from uiu.main import main

    ws = tmp_path / "ws"
    archive = _seed(ws)
    capsys.readouterr()

    # 破坏现场
    (ws / "sessions" / "important.json").unlink()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    rc = main(["--workspace", str(ws), "restore", str(archive)])
    captured = capsys.readouterr()
    assert rc == 2, f"非交互恢复应当失败，实际 rc={rc}"
    assert not (ws / "sessions" / "important.json").exists(), "不该悄悄恢复了"
    assert "--yes" in (captured.err + captured.out), captured


def test_restore_with_yes_actually_restores(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    archive = _seed(ws)
    capsys.readouterr()
    (ws / "sessions" / "important.json").unlink()
    (ws / "config.yaml").write_text("agent_name: broken\\n", encoding="utf-8")

    rc = main(["--workspace", str(ws), "restore", str(archive), "--yes"])
    assert rc == 0, capsys.readouterr()
    restored = ws / "sessions" / "important.json"
    assert restored.exists(), "带了 --yes 却没恢复"
    data = json.loads(restored.read_text(encoding="utf-8"))
    assert data["messages"][0]["content"] == "别弄丢我"
    # 恢复前必须自动做一份快照（可撤销）
    assert len(sorted((ws / "backups").glob("*.zip"))) >= 2


def test_sessions_prune_without_yes_in_a_pipe_fails_loudly(tmp_path, capsys, monkeypatch):
    from uiu import sessions as S
    from uiu.main import main

    ws = tmp_path / "ws"
    for i in range(4):
        S.save_session(ws, f"s{i}", [{"role": "user", "content": "x"}])
    capsys.readouterr()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    rc = main(["--workspace", str(ws), "sessions", "prune", "--keep", "1"])
    captured = capsys.readouterr()
    assert rc == 2, f"非交互裁剪应当失败，实际 rc={rc}"
    assert len(S.list_sessions(ws)) == 4, "不该悄悄删"
    assert "--yes" in (captured.err + captured.out), captured


def test_confirm_or_abort_tristate():
    """助手本身的三态语义固定住，避免以后被改回"一律 False"。"""
    from uiu import cli_shared

    assert cli_shared._confirm_or_abort("?", True, action="x") is True          # --yes
    # 非交互 → None（调用方据此返回非 0）
    import unittest.mock as mock

    with mock.patch.object(sys.stdin, "isatty", return_value=False):
        assert cli_shared._confirm_or_abort("?", False, action="x") is None


def test_confirm_or_abort_treats_eof_as_unconfirmable(monkeypatch):
    """实测坑：管道/CI 里 sys.stdin.isatty() 可能谎报 True，而 input() 立刻 EOF。

    这时不能当成「用户拒绝」，必须当成「无法确认」→ 调用方返回非 0。
    """
    import builtins

    from uiu import cli_shared

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)   # 谎报

    def _eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _eof)
    assert cli_shared._confirm_or_abort("?", False, action="x") is None


def test_confirm_or_abort_honours_an_explicit_no(monkeypatch):
    """交互终端里用户明确说 no → False（取消，调用方返回 0）。"""
    import builtins

    from uiu import cli_shared

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "n")
    assert cli_shared._confirm_or_abort("?", False, action="x") is False
    monkeypatch.setattr(builtins, "input", lambda prompt="": "y")
    assert cli_shared._confirm_or_abort("?", False, action="x") is True
