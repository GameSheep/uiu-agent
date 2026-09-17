"""Schema version + migration contract (audit §3.3)."""

from __future__ import annotations

import json

import pytest

from uiu import schema
from uiu._atomic import atomic_write_json


def test_current_versions_declared():
    assert schema.CURRENT == {"config": 1, "session": 1, "jobs": 1}
    for store in schema.STORES:
        assert schema.current(store) == 1


def test_detect_and_needs_migration():
    assert schema.detect("session", {"messages": []}) == 0
    assert schema.detect("session", {"schema": 1, "messages": []}) == 1
    assert schema.detect("session", {"schema": "2"}) == 2
    assert schema.detect("session", [{"role": "user"}]) == 0
    assert schema.needs_migration("session", {"messages": []}) is True
    assert schema.needs_migration("session", {"schema": 1}) is False


def test_migrate_is_idempotent():
    legacy = {"id": "s", "updated": 1.0, "messages": [{"role": "user", "content": "hi"}]}
    once, applied = schema.migrate("session", legacy)
    assert applied == ["session 0->1"]
    assert once["schema"] == 1
    twice, applied2 = schema.migrate("session", once)
    assert applied2 == []
    assert twice == once


def test_unknown_future_version_is_left_alone():
    payload = {"schema": 99, "messages": [{"role": "user"}]}
    out, applied = schema.migrate("session", payload)
    assert out == payload
    assert applied == []


def test_unknown_store_rejected():
    with pytest.raises(KeyError):
        schema.migrate("nope", {})


def test_bare_message_list_is_wrapped():
    out, _ = schema.migrate("session", [{"role": "user", "content": "x"}])
    assert out["schema"] == 1 and out["messages"][0]["content"] == "x"


# --------------------------------------------------------------------------
# 存储接线
# --------------------------------------------------------------------------


def test_saved_session_is_stamped(tmp_path):
    from uiu import sessions as S

    ws = tmp_path / "ws"
    S.save_session(ws, "s1", [{"role": "user", "content": "hi"}])
    raw = json.loads((S.sessions_dir(ws) / "s1.json").read_text(encoding="utf-8"))
    assert raw["schema"] == 1
    assert S.load_session(ws, "s1") == [{"role": "user", "content": "hi"}]


def test_legacy_session_reads_without_schema(tmp_path):
    from uiu import sessions as S

    ws = tmp_path / "ws"
    (ws / "sessions").mkdir(parents=True)
    atomic_write_json(ws / "sessions" / "old.json",
                      {"id": "old", "updated": 1.0,
                       "messages": [{"role": "user", "content": "legacy"}]})
    assert S.load_session(ws, "old") == [{"role": "user", "content": "legacy"}]
    assert [s["id"] for s in S.list_sessions(ws)] == ["old"]


def test_legacy_jobs_list_migrates_and_new_writes_are_v1(tmp_path):
    """jobs.json 从「顶层裸 list」变成 {schema, jobs} —— 老文件必须还能读。"""
    from uiu import cron

    ws = tmp_path / "ws"
    (ws / "cron").mkdir(parents=True)
    atomic_write_json(ws / "cron" / "jobs.json",
                      [{"id": "job-1", "name": "legacy", "schedule": "1d",
                        "task": "echo hi", "enabled": True, "next_run": 0}])
    jobs = cron.load_jobs(ws)
    assert [j["name"] for j in jobs] == ["legacy"]

    # 迁移后再写：必须是 v1 结构
    cron.set_enabled(ws, "legacy", False)
    raw = json.loads((ws / "cron" / "jobs.json").read_text(encoding="utf-8"))
    assert raw["schema"] == 1
    assert raw["jobs"][0]["enabled"] is False


def test_adding_to_legacy_jobs_does_not_drop_them(tmp_path):
    """最容易踩的坑：锁内读-改-写如果不先迁移，会把 v1 数据当空表清掉。"""
    from uiu import cron

    ws = tmp_path / "ws"
    cron.add_job(ws, "first", "1d", "echo 1")
    cron.add_job(ws, "second", "1d", "echo 2")
    names = sorted(j["name"] for j in cron.load_jobs(ws))
    assert names == ["first", "second"]
    assert cron.remove_job(ws, "first") is True
    assert [j["name"] for j in cron.load_jobs(ws)] == ["second"]


def test_config_is_stamped_and_legacy_config_is_migrated(tmp_path):
    from uiu import config as C

    ws = tmp_path / "ws"
    C.ensure_workspace(ws)
    cfg = C.load_config(ws)
    C.save_config(ws, cfg)
    text = (ws / "config.yaml").read_text(encoding="utf-8")
    assert "schema: 1" in text

    # 老配置（无 schema）读得出来，并会被补上版本号
    (ws / "config.yaml").write_text("agent_name: legacy\nmodel:\n  provider: openai\n",
                                    encoding="utf-8")
    assert C.load_config(ws).agent_name == "legacy"
    assert "schema: 1" in (ws / "config.yaml").read_text(encoding="utf-8")
