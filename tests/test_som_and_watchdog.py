"""Tests for Set-of-Mark (SoM) Visual Grounding, Process Watchdog, and Context Compaction."""

import json
import os
import pytest
from PIL import Image
from uiu.som_tagger import (
    SoMElement,
    _calculate_iou,
    render_som_tags,
    click_som_tag,
    capture_and_tag_screen,
)
from uiu.process_watchdog import (
    is_window_hung,
    ping_window_message_queue,
    get_window_process_info,
    check_app_health,
)
from uiu.context_compressor import (
    compress_tool_output,
    extract_trajectory_digest,
    compact_conversation_history,
)
from uiu.desktop_tools import dispatch_tool


def test_som_iou_calculation():
    box1 = [0, 0, 10, 10]
    box2 = [0, 0, 10, 10]
    assert _calculate_iou(box1, box2) == 1.0

    box_disjoint = [20, 20, 10, 10]
    assert _calculate_iou(box1, box_disjoint) == 0.0

    box_half = [0, 0, 10, 5]  # 50% overlap
    assert 0.45 <= _calculate_iou(box1, box_half) <= 0.55


def test_som_render_tags_and_catalog():
    test_img = Image.new("RGB", (300, 200), (50, 50, 50))
    elems = [
        SoMElement(tag_id=1, text="SaveButton", control_type="Button", box=[20, 20, 80, 30], center=[60, 35], source="uia"),
        SoMElement(tag_id=2, text="CancelLink", control_type="Hyperlink", box=[120, 20, 80, 30], center=[160, 35], source="ocr"),
    ]

    tagged_img, catalog = render_som_tags(image=test_img, elements=elems)
    assert tagged_img.size == (300, 200)
    assert len(catalog) == 2
    assert "1" in catalog and "2" in catalog
    assert catalog["1"].text == "SaveButton"
    assert catalog["2"].text == "CancelLink"


def test_click_som_tag_mocked(monkeypatch):
    import uiu.gui_primitives as gp
    clicks = []

    monkeypatch.setattr(gp, "mouse_click", lambda x, y, **kwargs: clicks.append((x, y)))

    # 1. Click existing tag
    res = click_som_tag("1", action="click", verify_change=False)
    assert res.startswith("[ok]")
    assert len(clicks) == 1

    # 2. Click missing tag
    res_err = click_som_tag("9999", action="click", verify_change=False)
    assert res_err.startswith("[error]")


def test_capture_and_tag_screen_markdown():
    # Calling on full screen or region produces markdown table
    md = capture_and_tag_screen(max_elements=10)
    assert isinstance(md, str)
    assert "Set-of-Mark" in md or "未检测到" in md


def test_process_watchdog_diagnostics():
    import win32gui
    hwnd = win32gui.GetDesktopWindow()

    # Desktop window is never hung
    assert is_window_hung(hwnd) is False
    assert ping_window_message_queue(hwnd) is True

    # Current process inspection
    pinfo = get_window_process_info(hwnd)
    assert isinstance(pinfo, dict)

    # Check app health
    health = check_app_health("NonExistentWindow98765")
    assert health["found"] is False


def test_context_compactor_and_rolling_checkpoint():
    # 1. Compress noisy tool output
    huge_ocr = "\n".join([f"| [{i}] | Button | Item {i} | (100, {i*10}) |" for i in range(100)])
    compressed = compress_tool_output("visual_tag_screen", huge_ocr)
    assert len(compressed) < len(huge_ocr)
    assert "[compacted]" in compressed

    # 2. Extract trajectory digest
    mock_messages = [
        {"role": "user", "content": "把 CC Switch 备注修改为 123"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "app_open_or_focus", "arguments": '{"app_name": "CC Switch"}'}}]},
        {"role": "tool", "content": "[ok] 成功聚焦 CC Switch"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "resilient_click", "arguments": '{"target": "Zhipu"}'}}]},
        {"role": "tool", "content": "[ok] 点击已完成"},
    ]
    digest = extract_trajectory_digest(mock_messages)
    assert "app_open_or_focus" in digest
    assert "resilient_click" in digest

    # 3. Compact conversation history
    long_history = [{"role": "system", "content": "System prompt"}]
    for i in range(30):
        long_history.append({"role": "user", "content": f"Turn {i} request"})
        long_history.append({"role": "assistant", "content": f"Turn {i} response " + "x" * 1500})

    compacted = compact_conversation_history(long_history, max_chars=10_000, keep_recent_turns=3)
    assert len(compacted) < len(long_history)
    assert compacted[0]["role"] == "system"
    assert "Rolling State Checkpoint" in compacted[2]["content"]


def test_desktop_tools_som_and_watchdog_dispatch():
    # Test visual_tag_screen dispatch
    res_tag = dispatch_tool("visual_tag_screen", {"max_elements": 5})
    assert isinstance(res_tag, str)

    # Test process_health_check dispatch
    res_health = dispatch_tool("process_health_check", {"target": "wechat", "auto_revive": False})
    assert res_health.startswith("[ok]")
