"""Workspace backup / restore contract (audit §3.4)."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import pytest

from uiu import backup
from uiu._atomic import atomic_write_json


def _seed(ws: Path) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "config.yaml").write_text("agent_name: uiu\nschema: 1\n", encoding="utf-8")
    # 注意：不要在这里写 OPENAI_API_KEY —— main() 会把 workspace/.env 载入 os.environ，
    # 会污染同进程后续测试（doctor 的 no-api-key 检查就是这么被带偏的）。
    (ws / ".env").write_text("SMOKE_TOKEN=test-token\n", encoding="utf-8")
    (ws / "MEMORY.md").write_text("- [2026-09-17] 记住了点什么\n", encoding="utf-8")
    (ws / "sessions").mkdir(exist_ok=True)
    atomic_write_json(ws / "sessions" / "s1.json", {"schema": 1, "messages": []})
    (ws / "cron").mkdir(exist_ok=True)
    (ws / "cron" / "jobs.json").write_text('{"schema": 1, "jobs": []}', encoding="utf-8")
    (ws / "skills" / "demo").mkdir(parents=True)
    (ws / "skills" / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    # 这些不该进备份
    (ws / "logs").mkdir(exist_ok=True)
    (ws / "logs" / "uiu.log").write_text("noise\n", encoding="utf-8")
    (ws / "cron" / "output").mkdir(exist_ok=True)
    (ws / "cron" / "output" / "run.md").write_text("artifact\n", encoding="utf-8")
    (ws / "sessions" / "s1.json.lock").write_text("", encoding="utf-8")


def test_backup_contains_state_and_skips_noise(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    path = backup.create_backup(ws)
    assert path.exists() and path.parent == backup.backup_dir(ws)

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        meta = json.loads(zf.read("BACKUP.json").decode("utf-8"))

    assert {"config.yaml", ".env", "MEMORY.md", "sessions/s1.json",
            "cron/jobs.json", "skills/demo/SKILL.md"} <= names
    assert not any(n.startswith("logs/") for n in names)
    assert not any(n.startswith("backups/") for n in names)
    assert not any(n.startswith("cron/output/") for n in names)
    assert not any(n.endswith(".lock") for n in names)
    assert meta["uiu_version"] and meta["files"] >= 6


def test_list_and_prune_keep_newest(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    made = []
    for i in range(4):
        p = backup.create_backup(ws)
        made.append(p)
        time.sleep(0.02)
        p.touch()

    listed = backup.list_backups(ws)
    assert len(listed) == 4
    assert listed[0].stat().st_mtime >= listed[-1].stat().st_mtime

    removed = backup.prune_backups(ws, keep=2)
    assert len(removed) == 2
    assert len(backup.list_backups(ws)) == 2
    assert made[0] not in backup.list_backups(ws), "应删最旧的"


def test_create_backup_keeps_only_n(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    for _ in range(5):
        backup.create_backup(ws, keep=2)
        time.sleep(0.01)
    assert len(backup.list_backups(ws)) == 2


def test_custom_target_does_not_touch_workspace_backups(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    backup.create_backup(ws)
    out = tmp_path / "elsewhere"
    path = backup.create_backup(ws, to=out, keep=1)
    assert path.parent == out
    assert len(backup.list_backups(ws)) == 1, "自定义目录不该裁剪 workspace 自己的备份"
    assert len(list(out.glob("uiu-backup-*.zip"))) == 1


def test_daily_backup_is_gated(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    first = backup.maybe_daily_backup(ws)
    assert first is not None
    assert backup.maybe_daily_backup(ws) is None, "24h 内不应重复备份"
    again = backup.maybe_daily_backup(ws, interval_hours=0)
    assert again is not None


def test_restore_roundtrip_and_safety_snapshot(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    archive = backup.create_backup(ws)

    (ws / "config.yaml").write_text("agent_name: broken\n", encoding="utf-8")
    (ws / "MEMORY.md").unlink()

    result = backup.restore_backup(ws, archive)
    assert (ws / "config.yaml").read_text(encoding="utf-8").startswith("agent_name: uiu")
    assert (ws / "MEMORY.md").exists()
    assert result["safety_backup"], "恢复前必须留一份快照"
    assert Path(result["safety_backup"]).exists()
    assert len(result["restored"]) >= 6


def test_restore_rejects_zip_slip(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../evil.txt", "pwned")
        zf.writestr("config.yaml", "agent_name: hijacked\n")

    before = (ws / "config.yaml").read_text(encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        backup.restore_backup(ws, evil)
    assert "越界" in str(exc.value)
    # 整体拒绝：不能写进任何一个文件
    assert (ws / "config.yaml").read_text(encoding="utf-8") == before
    assert not (tmp_path / "evil.txt").exists()


def test_restore_rejects_absolute_member(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws)
    evil = tmp_path / "abs.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("C:/Windows/evil.txt", "pwned")
    with pytest.raises(ValueError):
        backup.restore_backup(ws, evil)


def test_restore_missing_archive(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.restore_backup(tmp_path / "ws", tmp_path / "nope.zip")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_backup_and_restore(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    _seed(ws)
    assert main(["--workspace", str(ws), "backup"]) == 0
    out = capsys.readouterr().out
    assert "已备份" in out
    archives = backup.list_backups(ws)
    assert len(archives) == 1

    assert main(["--workspace", str(ws), "backup", "--list"]) == 0
    assert archives[0].name in capsys.readouterr().out

    (ws / "config.yaml").write_text("agent_name: nope\n", encoding="utf-8")
    assert main(["--workspace", str(ws), "restore", str(archives[0]), "--yes"]) == 0
    assert "已恢复" in capsys.readouterr().out
    assert (ws / "config.yaml").read_text(encoding="utf-8").startswith("agent_name: uiu")


def test_cli_restore_missing_file(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    _seed(ws)
    assert main(["--workspace", str(ws), "restore", str(tmp_path / "ghost.zip"), "--yes"]) == 2
    assert "找不到备份文件" in capsys.readouterr().err
