"""Cron advanced syntax tests — */n steps, ranges, lists, weekday matching."""

import time
from datetime import datetime

import pytest


def test_cron_step_parse():
    from uiu.cron import parse_schedule
    p = parse_schedule("*/15 9 * * *")
    assert p["kind"] == "cron"
    assert p["minutes"] == [0, 15, 30, 45]
    assert p["hours"] == [9]


def test_cron_range_and_list():
    from uiu.cron import parse_schedule
    p = parse_schedule("0 9-11 * * 1-5")
    assert p["kind"] == "cron"
    assert p["hours"] == [9, 10, 11]
    assert p["dows"] == [1, 2, 3, 4, 5]
    p2 = parse_schedule("0,30 * * * *")
    assert p2["minutes"] == [0, 30]


def test_cron_invalid_rejected():
    from uiu.cron import parse_schedule
    with pytest.raises(ValueError):
        parse_schedule("99 * * * *")   # 分超界
    with pytest.raises(ValueError):
        parse_schedule("*/0 * * * *")  # 步长 0
    with pytest.raises(ValueError):
        parse_schedule("* * *")        # 字段不足


def test_next_run_weekday_forward():
    """Every weekday 09:00 from a known Sunday must land Monday 09:00."""
    from uiu.cron import parse_schedule, next_run_after
    p = parse_schedule("0 9 * * 1-5")
    # 2026-09-06 is a Sunday
    sunday = datetime(2026, 9, 6, 10, 0).timestamp()
    nxt = next_run_after(p, sunday)
    dt = datetime.fromtimestamp(nxt)
    assert dt.weekday() == 0 and dt.hour == 9 and dt.minute == 0, dt


def test_next_run_same_day_later():
    from uiu.cron import parse_schedule, next_run_after
    p = parse_schedule("30 14 * * *")  # 每天 14:30
    before = datetime(2026, 9, 7, 10, 0).timestamp()   # 当天较早
    assert datetime.fromtimestamp(next_run_after(p, before)).hour == 14
    after = datetime(2026, 9, 7, 15, 0).timestamp()    # 当天已过 → 次日
    assert datetime.fromtimestamp(next_run_after(p, after)).day == 8


def test_cron_step_every_2_hours():
    from uiu.cron import parse_schedule, next_run_after
    p = parse_schedule("0 */2 * * *")
    base = datetime(2026, 9, 7, 5, 10).timestamp()
    nxt = datetime.fromtimestamp(next_run_after(p, base))
    assert nxt.hour == 6, nxt


def test_next_run_sunday_cron_0():
    """cron dow 0/7 = Sunday. From a Friday, `0 9 * * 0` lands Sunday 09:00."""
    from uiu.cron import parse_schedule, next_run_after
    p = parse_schedule("0 9 * * 0")
    fri = datetime(2026, 9, 4, 10, 0).timestamp()  # 2026-09-04 is a Friday
    nxt = datetime.fromtimestamp(next_run_after(p, fri))
    assert nxt.weekday() == 6 and nxt.day == 6 and nxt.hour == 9, nxt


def test_cron_saturday_6():
    """cron dow 6 = Saturday. From a Sunday, `0 9 * * 6` lands next Saturday."""
    from uiu.cron import parse_schedule, next_run_after
    p = parse_schedule("0 9 * * 6")
    sun = datetime(2026, 9, 6, 10, 0).timestamp()
    nxt = datetime.fromtimestamp(next_run_after(p, sun))
    assert nxt.weekday() == 5 and nxt.hour == 9, nxt


def test_help_text_mentions_advanced_cron():
    from uiu.slash import help_text
    assert "dom" in help_text() or "cron" in help_text()
