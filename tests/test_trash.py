"""回收站与撤销（审计 §4.1）：删除必须可撤销。"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from uiu import trash
from uiu._atomic import atomic_write_json


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "sessions").mkdir(parents=True)
    return ws


# --------------------------------------------------------------------------
# 回收站基本语义
# --------------------------------------------------------------------------


def test_file_roundtrip(tmp_path):
    ws = _ws(tmp_path)
    victim = ws / "sessions" / "s1.json"
    atomic_write_json(victim, {"schema": 1, "messages": []})

    meta = trash.add_file(ws, victim, kind="session", label="s1")
    assert meta["id"] and meta["origin"] == "sessions/s1.json"
    assert not victim.exists(), "删除后原文件不该还在"
    assert [e["id"] for e in trash.list_entries(ws)] == [meta["id"]]

    ok, msg = trash.restore(ws, meta["id"])
    assert ok and "已恢复" in msg
    assert victim.exists() and json.loads(victim.read_text(encoding="utf-8"))["schema"] == 1
    assert trash.list_entries(ws) == [], "恢复后条目应被清掉"


def test_restore_refuses_to_overwrite(tmp_path):
    ws = _ws(tmp_path)
    victim = ws / "sessions" / "s1.json"
    victim.write_text("old", encoding="utf-8")
    meta = trash.add_file(ws, victim, kind="session", label="s1")
    victim.write_text("new", encoding="utf-8")          # 同名的又出现了

    ok, msg = trash.restore(ws, meta["id"])
    assert ok is False and "原位置已有同名文件" in msg
    assert victim.read_text(encoding="utf-8") == "new", "不能覆盖已有文件"


def test_missing_entry_is_reported(tmp_path):
    ws = _ws(tmp_path)
    ok, msg = trash.restore(ws, "20260101-nope")
    assert ok is False and "没有" in msg


def test_purge_drops_old_entries(tmp_path):
    ws = _ws(tmp_path)
    victim = ws / "sessions" / "old.json"
    victim.write_text("x", encoding="utf-8")
    meta = trash.add_file(ws, victim, kind="session", label="old")

    # 把 created 改成 10 天前
    meta_file = trash.trash_dir(ws) / meta["id"] / "meta.json"
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    data["created"] = time.time() - 10 * 86400
    atomic_write_json(meta_file, data)

    removed = trash.purge(ws, days=7)
    assert removed == [meta["id"]]
    assert trash.list_entries(ws) == []


def test_purge_keeps_fresh_entries(tmp_path):
    ws = _ws(tmp_path)
    victim = ws / "sessions" / "fresh.json"
    victim.write_text("x", encoding="utf-8")
    trash.add_file(ws, victim, kind="session", label="fresh")
    assert trash.purge(ws, days=7) == []
    assert len(trash.list_entries(ws)) == 1


# --------------------------------------------------------------------------
# 各类删除都走回收站
# --------------------------------------------------------------------------


def test_session_delete_is_recoverable(tmp_path):
    from uiu import sessions as S

    ws = tmp_path / "ws"
    S.save_session(ws, "keep", [{"role": "user", "content": "1"}])
    S.save_session(ws, "doomed", [{"role": "user", "content": "2"}])

    assert S.remove_session(ws, "doomed") is True
    assert [s["id"] for s in S.list_sessions(ws)] == ["keep"]

    entry = trash.list_entries(ws)[0]
    assert entry["kind"] == "session" and entry["label"] == "doomed"
    ok, _ = trash.restore(ws, entry["id"])
    assert ok
    assert sorted(s["id"] for s in S.list_sessions(ws)) == ["doomed", "keep"]
    assert S.load_session(ws, "doomed") == [{"role": "user", "content": "2"}]


def test_macro_delete_is_recoverable(tmp_path, monkeypatch):
    from uiu import macros

    ws = tmp_path / "ws"
    (ws / "macros").mkdir(parents=True)
    macro = ws / "macros" / "demo.json"
    atomic_write_json(macro, [{"action": "click", "x": 1, "y": 2}])
    monkeypatch.setenv("UIU_WORKSPACE", str(ws))

    out = macros.macro_remove("demo")
    assert out.startswith("[ok]") and "回收站" in out
    assert not macro.exists()
    assert trash.list_entries(ws)

    ok, _ = trash.restore(ws, trash.list_entries(ws)[0]["id"])
    assert ok and macro.exists()


def test_channel_record_restore(tmp_path, monkeypatch):
    from uiu.config import ChannelConfig, load_config, save_config, ensure_workspace

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    meta = trash.add_record(ws, "channel",
                            {"type": "webhook", "name": "ext", "enabled": True,
                             "secret_env": "", "options": {"secret": "s"}},
                            label="ext")
    cfg = load_config(ws)
    assert [c.name for c in cfg.channels] == []
    ok, msg = trash.restore(ws, meta["id"])
    assert ok, msg
    assert [c.name for c in load_config(ws).channels] == ["ext"]


def test_cron_job_record_restore(tmp_path):
    from uiu import cron

    ws = tmp_path / "ws"
    job = cron.add_job(ws, "nightly", "1d", "echo hi")
    meta = trash.add_record(ws, "cron_job", job, label="nightly")
    assert cron.remove_job(ws, job["id"]) is True
    assert cron.load_jobs(ws) == []

    ok, msg = trash.restore(ws, meta["id"])
    assert ok, msg
    assert [j["name"] for j in cron.load_jobs(ws)] == ["nightly"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_trash_list_restore_purge(tmp_path, capsys):
    from uiu import sessions as S
    from uiu.main import main

    ws = tmp_path / "ws"
    S.save_session(ws, "doomed", [{"role": "user", "content": "x"}])
    S.remove_session(ws, "doomed")

    assert main(["--workspace", str(ws), "trash"]) == 0
    out = capsys.readouterr().out
    assert "doomed" in out

    entry_id = trash.list_entries(ws)[0]["id"]
    assert main(["--workspace", str(ws), "trash", "--restore", entry_id]) == 0
    assert "已恢复" in capsys.readouterr().out
    assert S.load_session(ws, "doomed") is not None

    assert main(["--workspace", str(ws), "trash", "--restore", "ghost"]) == 2
    assert "没有" in capsys.readouterr().err

    # 再来一条并把它做旧，--purge 才会真的清
    S.save_session(ws, "again", [{"role": "user", "content": "y"}])
    S.remove_session(ws, "again")
    entry = trash.list_entries(ws)[0]
    meta_file = trash.trash_dir(ws) / entry["id"] / "meta.json"
    data = json.loads(meta_file.read_text(encoding="utf-8"))
    data["created"] = time.time() - 30 * 86400
    atomic_write_json(meta_file, data)

    assert main(["--workspace", str(ws), "trash", "--purge", "--days", "7"]) == 0
    assert "已清理" in capsys.readouterr().out
    assert trash.list_entries(ws) == []


def test_cli_sessions_remove_goes_to_trash(tmp_path, capsys):
    from uiu import sessions as S
    from uiu.main import main

    ws = tmp_path / "ws"
    S.save_session(ws, "tmp1", [{"role": "user", "content": "x"}])
    assert main(["--workspace", str(ws), "sessions", "remove", "tmp1"]) == 0
    assert trash.list_entries(ws), "CLI 删除也应该进回收站"


# --------------------------------------------------------------------------
# TUI：Ctrl+Z 撤销删除
# --------------------------------------------------------------------------


def test_tui_ctrl_z_restores_deleted_session(tmp_path):
    from uiu import sessions as S
    from uiu.app import UiuApp
    from uiu.app.widgets import StatusBar
    from uiu.workspace import Workspace

    class _Stub:
        pass

    ws_dir = tmp_path / "ws"
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        ws_dir.mkdir(parents=True, exist_ok=True)
        (ws_dir / name).write_text("# " + name, encoding="utf-8")
    S.save_session(ws_dir, "keep", [{"role": "user", "content": "1"}])
    S.save_session(ws_dir, "doomed", [{"role": "user", "content": "2"}])
    ws = Workspace(root=ws_dir, soul="s", identity="i", user="u", memory="m", skills=[])

    async def _impl():
        app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("ctrl+x")
            await pilot.pause(0.5)
            modal = app.screen_stack[-1]
            ids = [s["id"] for s in modal._sessions]
            modal.query_one("#session-list").index = ids.index("doomed")
            await pilot.press("d")
            await pilot.pause(0.5)
            assert S.load_session(ws_dir, "doomed") is None
            assert trash.list_entries(ws_dir), "删除应进回收站"

            await pilot.press("escape")
            await pilot.pause(0.3)
            await pilot.press("ctrl+z")
            await pilot.pause(0.6)
            assert S.load_session(ws_dir, "doomed") is not None, "Ctrl+Z 应该把它找回来"
            assert "已恢复" in app.query_one("#status", StatusBar).toast

    asyncio.run(_impl())
