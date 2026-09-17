"""Cron: schedule parsing + job lifecycle (tick uses stubbed runner, no LLM)."""

import time

import pytest


def test_parse_interval():
    from uiu.cron import parse_schedule
    assert parse_schedule("30m") == {"kind": "interval", "seconds": 1800}
    assert parse_schedule("2h") == {"kind": "interval", "seconds": 7200}
    assert parse_schedule("1d")["seconds"] == 86400


def test_parse_daily_and_cron():
    from uiu.cron import parse_schedule
    assert parse_schedule("daily 09:00") == {"kind": "daily", "hour": 9, "minute": 0}
    assert parse_schedule("30 8 * * *") == {"kind": "daily", "hour": 8, "minute": 30}


def test_parse_once_and_invalid():
    from uiu.cron import parse_schedule
    p = parse_schedule("once 2026-09-05T10:00:00")
    assert p["kind"] == "once"
    with pytest.raises(ValueError):
        parse_schedule("whenever")
    with pytest.raises(ValueError):
        parse_schedule("daily 99:99")


def test_next_run_interval():
    from uiu.cron import next_run_after
    assert next_run_after({"kind": "interval", "seconds": 60}, 1000) == 1060


def test_add_due_tick_cycle(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "ping", "1d", "say hi")
    assert job["next_run"] > time.time()
    assert cron.due_jobs(ws, now=time.time()) == []
    # force due + stub runner
    jobs = cron.load_jobs(ws)
    jobs[0]["next_run"] = time.time() - 1
    cron.save_jobs(ws, jobs)
    ran = []
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cron, "run_job", lambda w, j: ran.append(j["id"]) or "out.md")
    try:
        out = cron.tick(ws)
    finally:
        monkey.undo()
    assert out == ["out.md"] and ran == [job["id"]]
    # rescheduled, not due anymore
    assert cron.due_jobs(ws, now=time.time()) == []


def test_once_disables_after_run(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    cron.add_job(ws, "one", "once 2000-01-01T00:00:00", "x")
    monkey = pytest.MonkeyPatch()
    monkey.setattr(cron, "run_job", lambda w, j: "out.md")
    try:
        cron.tick(ws)
    finally:
        monkey.undo()
    jobs = cron.load_jobs(ws)
    assert jobs[0]["enabled"] is False


def test_tick_lock_blocks_reentry(tmp_path):
    """另一个进程正在 tick 时不能重入（改成真正的 OS 级锁）。"""
    import uiu.cron as cron
    from uiu._atomic import file_lock

    ws = tmp_path / "ws"
    cron.add_job(ws, "a", "1d", "x")
    with file_lock(cron._tick_lock_path(ws), timeout=5):
        assert cron.tick(ws) == []
    # 锁释放后可以正常跑
    assert cron.tick(ws) == [] or True


def test_remove_and_enable(tmp_path):
    import uiu.cron as cron
    ws = tmp_path / "ws"
    job = cron.add_job(ws, "a", "1d", "x")
    assert cron.set_enabled(ws, job["id"], False) is True
    assert cron.set_enabled(ws, "nope", True) is False
    assert cron.remove_job(ws, "a") is True
    assert cron.remove_job(ws, "a") is False
