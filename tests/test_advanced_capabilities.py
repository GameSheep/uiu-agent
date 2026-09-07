"""Tests for Advanced Capabilities: IME Controller, Spatial Locator, Task Checkpoints, Scroll Probe, Safety HUD, and CDP."""

import json
import time
import pytest
from uiu.ime_controller import (
    set_ime_to_english,
    get_ime_conversion_status,
    preserve_ime_mode,
)
from uiu.spatial_locator import (
    BoundingBox,
    match_spatial_relation,
    find_element_by_relation,
)
from uiu.task_checkpoint import (
    CheckpointEntry,
    record_step_start,
    record_step_finish,
    load_task_checkpoints,
    list_incomplete_tasks,
    rollback_task,
)
from uiu.scroll_probe import scroll_and_find
from uiu.safety_hud import (
    is_emergency_stop_triggered,
    trigger_emergency_stop,
    reset_emergency_stop,
)
from uiu.cdp_controller import (
    is_cdp_available,
    list_browser_tabs,
    get_browser_dom_text,
    click_dom_element,
)
from uiu.desktop_tools import dispatch_tool


def test_ime_controller():
    # Calling on current process/foreground
    res = set_ime_to_english()
    assert isinstance(res, bool)

    with preserve_ime_mode():
        pass


def test_spatial_locator_relations():
    # Anchor: [100, 100, 80, 30] -> right=180, bottom=130, cx=140, cy=115
    anchor = BoundingBox(left=100, top=100, width=80, height=30, text="Zhipu GLM")

    # 1. Target right
    target_right = BoundingBox(left=190, top=100, width=50, height=30, text="Edit")
    dist_r = match_spatial_relation(anchor, target_right, relation="right")
    assert dist_r is not None and dist_r > 0

    # Target left (should not match right relation)
    target_left = BoundingBox(left=20, top=100, width=50, height=30, text="Back")
    assert match_spatial_relation(anchor, target_left, relation="right") is None

    # 2. Target below
    target_below = BoundingBox(left=100, top=140, width=80, height=30, text="InputBox")
    dist_b = match_spatial_relation(anchor, target_below, relation="below")
    assert dist_b is not None and dist_b > 0

    # 3. Target inside
    target_inside = BoundingBox(left=110, top=105, width=20, height=20, text="Icon")
    dist_in = match_spatial_relation(anchor, target_inside, relation="inside")
    assert dist_in == 0.0


def test_task_checkpoint_wal(tmp_path, monkeypatch):
    import uiu.task_checkpoint as tc

    monkeypatch.setattr(tc, "_get_checkpoint_dir", lambda: tmp_path)

    test_tid = "test_task_wal_123"
    goal = "测试任务断点与回滚"

    # Step 1 start and finish
    e1 = record_step_start(test_tid, goal, 1, "app_open_or_focus", {"app_name": "CC Switch"})
    assert e1.status == "started"

    e1_f = record_step_finish(
        test_tid, 1, "[ok] 打开成功",
        status="completed",
        undo_action={"tool_name": "window_close", "tool_args": {"title_keyword": "CC Switch"}},
    )
    assert e1_f.status == "completed"

    # Verify loaded checkpoints
    entries = load_task_checkpoints(test_tid)
    assert len(entries) == 2
    assert entries[0].step_index == 1

    # Incomplete listing
    tasks = list_incomplete_tasks()
    assert len(tasks) >= 1
    assert tasks[0]["task_id"] == test_tid

    # Rollback execution
    roll_res = rollback_task(test_tid)
    assert roll_res.startswith("[ok]") or roll_res.startswith("[warning]")


def test_scroll_probe_boundary(monkeypatch):
    from PIL import Image
    import uiu.scroll_probe as sp

    # Mock screen grab returning identical images -> should hit boundary immediately
    mock_img = Image.new("RGB", (100, 100), (20, 20, 20))
    monkeypatch.setattr("uiu.screen_tools.safe_screenshot", lambda **kw: mock_img)
    monkeypatch.setattr("uiu.gui_primitives.mouse_scroll", lambda *args, **kw: None)

    res = scroll_and_find(target="__NON_EXISTENT_TXT_12345__", max_scrolls=3)
    assert res["found"] is False
    assert res["hit_boundary"] is True


def test_safety_hud_emergency_stop():
    reset_emergency_stop()
    assert is_emergency_stop_triggered() is False

    trigger_emergency_stop("pytest test panic")
    assert is_emergency_stop_triggered() is True

    reset_emergency_stop()
    assert is_emergency_stop_triggered() is False


def test_cdp_controller_fallback():
    # If Chrome remote debugging is not running on 9222 (standard test env)
    avail = is_cdp_available(port=9222)
    assert isinstance(avail, bool)

    tabs = list_browser_tabs(port=9222)
    assert isinstance(tabs, list)

    res_dom = get_browser_dom_text(port=9222)
    assert "[ok]" in res_dom or "[error]" in res_dom

    res_click = click_dom_element("#submit-btn", port=9222)
    assert "[ok]" in res_click or "[error]" in res_click or "[warning]" in res_click


def test_desktop_tools_advanced_dispatch():
    # 1. Test spatial_anchor_find dispatch (non-existent targets cleanly return warning)
    res_spat = dispatch_tool("spatial_anchor_find", {"target": "Edit", "anchor": "NonExistentAnchor", "relation": "right"})
    assert "[warning]" in res_spat or "[ok]" in res_spat

    # 2. Test task_checkpoint_manage dispatch
    res_chk = dispatch_tool("task_checkpoint_manage", {"action": "list_incomplete"})
    assert res_chk.startswith("[ok]")

    # 3. Test browser_cdp_action dispatch
    res_cdp = dispatch_tool("browser_cdp_action", {"action": "status"})
    assert res_cdp.startswith("[ok]")
