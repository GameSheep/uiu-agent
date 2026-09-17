"""会话生命周期与空间管理（审计 §3.5）。

会话只增不减会给真实用户带来两个问题：磁盘越吃越多、切换器越来越长。
这里约定：**看得见**（usage）＋**裁得掉**（prune，且进回收站可恢复）＋**不擅自删**（默认只告警）。
"""

from __future__ import annotations

import json
import time

import pytest

from uiu import sessions as S
from uiu import trash


def _seed(ws, n: int, *, size=200):
    for i in range(n):
        S.save_session(ws, f"s{i:02d}", [{"role": "user", "content": "x" * size}])
        time.sleep(0.01)          # 保证 updated/mtime 有区分度


# --------------------------------------------------------------------------
# 占用统计
# --------------------------------------------------------------------------


def test_usage_reports_count_bytes_and_largest(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 3, size=100)
    S.save_session(ws, "big", [{"role": "user", "content": "y" * 5000}])

    usage = S.sessions_usage(ws)
    assert usage["count"] == 4
    assert usage["bytes"] > 5000
    assert usage["largest"][0]["id"] == "big"
    assert usage["newest"] and usage["oldest"]


def test_list_sessions_includes_size(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 1)
    rows = S.list_sessions(ws)
    assert rows[0]["bytes"] > 0


# --------------------------------------------------------------------------
# 裁剪：进回收站、可恢复、不碰受保护的会话
# --------------------------------------------------------------------------


def test_prune_keeps_newest_and_uses_trash(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 6)
    plan = S.prune_sessions(ws, keep=2, protect=("default",))
    assert len(plan["removed"]) == 4
    assert plan["kept"] == 2

    remaining = {s["id"] for s in S.list_sessions(ws)}
    assert remaining == {"s04", "s05"}, remaining
    # 可恢复
    entries = trash.list_entries(ws)
    assert {e["label"] for e in entries} == {"s00", "s01", "s02", "s03"}
    ok, _ = trash.restore(ws, entries[0]["id"])
    assert ok
    assert len(S.list_sessions(ws)) == 3


def test_prune_by_age(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 3)
    # 把最旧的两条做旧
    for sid in ("s00", "s01"):
        path = S.sessions_dir(ws) / f"{sid}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["updated"] = time.time() - 30 * 86400
        path.write_text(json.dumps(data), encoding="utf-8")

    plan = S.prune_sessions(ws, keep=0, max_age_days=7)
    assert sorted(plan["removed"]) == ["s00", "s01"]
    assert {s["id"] for s in S.list_sessions(ws)} == {"s02"}


def test_prune_requires_both_conditions_when_both_given(tmp_path):
    """同时给 keep 与 days 时：既超量、又超龄才裁（更保守）。"""
    ws = tmp_path / "ws"
    _seed(ws, 4)                      # s00..s03，最新的在后
    path = S.sessions_dir(ws) / "s00.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["updated"] = time.time() - 30 * 86400
    path.write_text(json.dumps(data), encoding="utf-8")

    plan = S.prune_sessions(ws, keep=2, max_age_days=7)
    assert plan["removed"] == ["s00"], plan       # 超量的 s01/s02 还没超龄 → 保留


def test_prune_protects_named_sessions(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 3)
    plan = S.prune_sessions(ws, keep=1, protect=("s00",))
    assert "s00" not in plan["removed"]
    assert "s00" in {s["id"] for s in S.list_sessions(ws)}


def test_dry_run_touches_nothing(tmp_path):
    ws = tmp_path / "ws"
    _seed(ws, 4)
    plan = S.prune_sessions(ws, keep=1, dry_run=True)
    assert len(plan["removed"]) == 3 and plan["dry_run"] is True
    assert len(S.list_sessions(ws)) == 4, "dry-run 不能真的删"
    assert trash.list_entries(ws) == []


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_usage_and_list(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    _seed(ws, 2)
    assert main(["--workspace", str(ws), "sessions", "usage"]) == 0
    out = capsys.readouterr().out
    assert "会话数: 2" in out and "MB" in out

    assert main(["--workspace", str(ws), "sessions", "list"]) == 0
    out = capsys.readouterr().out
    assert "KB" in out and "共 2 个" in out


def test_cli_prune_dry_run_then_yes(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    _seed(ws, 5)
    assert main(["--workspace", str(ws), "sessions", "prune", "--keep", "1",
                 "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert len(S.list_sessions(ws)) == 5

    assert main(["--workspace", str(ws), "sessions", "prune", "--keep", "1", "--yes"]) == 0
    assert "已裁剪" in capsys.readouterr().out
    assert len(S.list_sessions(ws)) == 1
    assert len(trash.list_entries(ws)) == 4


def test_cli_prune_noop_when_within_limits(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "ws"
    _seed(ws, 2)
    assert main(["--workspace", str(ws), "sessions", "prune", "--keep", "10"]) == 0
    assert "无需裁剪" in capsys.readouterr().out
    assert len(S.list_sessions(ws)) == 2


# --------------------------------------------------------------------------
# 配置与 daemon 行为
# --------------------------------------------------------------------------


def test_config_fields_roundtrip_and_legacy_default(tmp_path):
    from uiu.config import ensure_workspace, load_config, save_config

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    cfg = load_config(ws)
    assert cfg.sessions_keep == 200 and cfg.sessions_auto_prune is False

    cfg.sessions_keep = 5
    cfg.sessions_auto_prune = True
    cfg.sessions_max_age_days = 30.0
    save_config(ws, cfg)
    again = load_config(ws)
    assert (again.sessions_keep, again.sessions_auto_prune,
            again.sessions_max_age_days) == (5, True, 30.0)


def test_daemon_warns_but_does_not_delete_by_default(tmp_path, monkeypatch):
    from uiu import daemon
    from uiu.config import ensure_workspace, load_config, save_config

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    monkeypatch.setenv("UIU_HOME", str(tmp_path / "home"))
    _seed(ws, 4)
    cfg = load_config(ws)
    cfg.sessions_keep = 2                    # 上限调到 2，触发告警
    cfg.sessions_auto_prune = False          # 但没开自动裁剪
    save_config(ws, cfg)

    import threading

    stop = threading.Event()
    stop.set()
    daemon.run_daemon(ws, interval=0.01, stop_event=stop)

    assert len(S.list_sessions(ws)) == 4, "默认绝不擅自删用户会话"
    from uiu.log import log_path
    body = log_path(ws).read_text(encoding="utf-8")
    assert "超过上限" in body and "sessions prune" in body


def test_daemon_auto_prune_when_enabled(tmp_path, monkeypatch):
    from uiu import daemon
    from uiu.config import ensure_workspace, load_config, save_config

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    monkeypatch.setenv("UIU_HOME", str(tmp_path / "home"))
    _seed(ws, 4)
    cfg = load_config(ws)
    cfg.sessions_keep = 2
    cfg.sessions_auto_prune = True
    save_config(ws, cfg)

    import threading

    stop = threading.Event()
    stop.set()
    daemon.run_daemon(ws, interval=0.01, stop_event=stop)

    assert len(S.list_sessions(ws)) == 2
    assert len(trash.list_entries(ws)) == 2, "自动裁剪也必须进回收站"


# --------------------------------------------------------------------------
# TUI 提示与 doctor
# --------------------------------------------------------------------------


def test_tui_switcher_shows_usage(tmp_path):
    import asyncio

    from uiu.app import UiuApp
    from uiu.workspace import Workspace

    class _Stub:
        pass

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir(parents=True)
    for name in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        (ws_dir / name).write_text("# " + name, encoding="utf-8")
    _seed(ws_dir, 3)
    ws = Workspace(root=ws_dir, soul="s", identity="i", user="u", memory="m", skills=[])

    async def _impl():
        app = UiuApp(_Stub(), ws, model="m", cfg=None, app_cfg=None)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.4)
            await pilot.press("ctrl+x")
            await pilot.pause(0.5)
            modal = app.screen_stack[-1]
            foot = str(modal.query_one("#session-foot").render())
            assert "3 个" in foot and "MB" in foot, foot
            from textual.widgets import Label as _Label
            body = " ".join(str(lbl.render()) for lbl in modal.query(_Label))
            assert "KB" in body, body

    asyncio.run(_impl())


def test_doctor_flags_over_cap_sessions(tmp_path):
    from uiu import doctor
    from uiu.config import ensure_workspace, load_config, save_config

    ws = tmp_path / "ws"
    ensure_workspace(ws)
    _seed(ws, 3)
    cfg = load_config(ws)
    cfg.sessions_keep = 1
    save_config(ws, cfg)

    items = doctor._all_checks(ws)
    finding = next((f for f in items if f.id == "sessions/over-cap"), None)
    assert finding is not None, [f.id for f in items]
    assert finding.severity == "info"
    assert "uiu sessions prune" in finding.fix_hint
