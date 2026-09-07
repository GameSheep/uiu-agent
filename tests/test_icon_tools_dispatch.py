"""Tests for icon & UIA tools dispatch and fast pipeline integration."""

import json
from unittest.mock import patch


def test_dispatch_screen_icon_find():
    from uiu.desktop_tools import dispatch_tool

    mock_match = {"found": True, "cx": 450, "cy": 220, "score": 0.88}
    with patch("uiu.icon_locator.match_icon_template", return_value=mock_match):
        out = dispatch_tool("screen_icon_find", {"icon_name": "pencil"})
        data = json.loads(out)
        assert data["found"] is True
        assert data["x"] == 450
        assert data["y"] == 220


def test_dispatch_screen_icon_find_by_anchor():
    from uiu.desktop_tools import dispatch_tool

    mock_anchor_res = {"found": True, "cx": 680, "cy": 310, "index": 2}
    with patch("uiu.icon_locator.find_icons_relative_to_anchor", return_value=mock_anchor_res):
        out = dispatch_tool("screen_icon_find", {"anchor_text": "Zhipu GLM", "direction": "right", "index": 2})
        data = json.loads(out)
        assert data["found"] is True
        assert data["x"] == 680
        assert data["y"] == 310


def test_dispatch_ui_control_find():
    from uiu.desktop_tools import dispatch_tool

    mock_ctrl = {"found": True, "name": "保存", "control_type": "ButtonControl", "cx": 700, "cy": 850}
    with patch("uiu.uia_locator.find_uia_control", return_value=mock_ctrl):
        out = dispatch_tool("ui_control_find", {"name": "保存", "control_type": "Button"})
        data = json.loads(out)
        assert data["found"] is True
        assert data["x"] == 700
        assert data["y"] == 850


def test_gui_action_pipeline_icon_steps():
    from uiu.fast_pipeline import gui_action_pipeline

    steps = [
        {"action": "click_icon", "icon": "pencil"},
        {"action": "click_icon_near", "anchor": "Zhipu GLM", "direction": "right", "index": 1},
        {"action": "click_uia", "name": "编辑", "control_type": "Button"},
    ]

    with patch("uiu.icon_locator.match_icon_template", return_value={"cx": 100, "cy": 100}), \
         patch("uiu.icon_locator.find_icons_relative_to_anchor", return_value={"cx": 200, "cy": 200}), \
         patch("uiu.uia_locator.find_uia_control", return_value={"cx": 300, "cy": 300}), \
         patch("uiu.gui_primitives.mouse_click", return_value="clicked"):
        report = gui_action_pipeline(steps)
        assert "Step 1 [click_icon]" in report
        assert "Step 2 [click_icon_near]" in report
        assert "Step 3 [click_uia]" in report
