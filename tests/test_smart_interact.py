"""Tests for smart_interact unified self-healing interaction engine."""

import json
from unittest.mock import patch


def test_smart_interact_tier1_uia():
    from uiu.smart_interact import smart_interact

    mock_uia = {"name": "保存", "control_type": "ButtonControl", "cx": 150, "cy": 250}
    with patch("uiu.uia_locator.find_uia_control", return_value=mock_uia), \
         patch("uiu.gui_primitives.mouse_click", return_value="clicked"):
        res = smart_interact("保存", action="click", verify_change=False)
        assert res["success"] is True
        assert res["tier_used"] == "uia"
        assert res["x"] == 150
        assert res["y"] == 250


def test_smart_interact_tier2_ocr_fallback():
    from uiu.smart_interact import smart_interact

    mock_ocr = {"text": "设置", "cx": 320, "cy": 480}
    with patch("uiu.uia_locator.find_uia_control", return_value=None), \
         patch("uiu.vision_locator.locate_text_on_screen", return_value=mock_ocr), \
         patch("uiu.gui_primitives.mouse_click", return_value="clicked"):
        res = smart_interact("设置", action="click", verify_change=False)
        assert res["success"] is True
        assert res["tier_used"] == "ocr"
        assert res["x"] == 320
        assert res["y"] == 480


def test_smart_interact_tier3_anchor_icon_fallback():
    from uiu.smart_interact import smart_interact

    mock_anchor = {"cx": 550, "cy": 300, "index": 2}
    with patch("uiu.uia_locator.find_uia_control", return_value=None), \
         patch("uiu.vision_locator.locate_text_on_screen", return_value=None), \
         patch("uiu.icon_locator.find_icons_relative_to_anchor", return_value=mock_anchor), \
         patch("uiu.gui_primitives.mouse_click", return_value="clicked"):
        res = smart_interact({"anchor": "Zhipu GLM", "near_icon": 2}, action="click", verify_change=False)
        assert res["success"] is True
        assert res["tier_used"] == "icon_anchor"
        assert res["x"] == 550


def test_smart_interact_tier4_template_fallback():
    from uiu.smart_interact import smart_interact

    mock_tpl = {"cx": 700, "cy": 120, "score": 0.89}
    with patch("uiu.uia_locator.find_uia_control", return_value=None), \
         patch("uiu.vision_locator.locate_text_on_screen", return_value=None), \
         patch("uiu.icon_locator.match_icon_template", return_value=mock_tpl), \
         patch("uiu.gui_primitives.mouse_click", return_value="clicked"):
        res = smart_interact("pencil", action="click", verify_change=False)
        assert res["success"] is True
        assert res["tier_used"] == "icon_template"
        assert res["x"] == 700


def test_smart_interact_all_fail():
    from uiu.smart_interact import smart_interact

    with patch("uiu.uia_locator.find_uia_control", return_value=None), \
         patch("uiu.vision_locator.locate_text_on_screen", return_value=None), \
         patch("uiu.icon_locator.match_icon_template", return_value=None):
        res = smart_interact("不存在的按钮", action="click", verify_change=False)
        assert res["success"] is False
        assert "未能定位目标" in res["message"]


def test_dispatch_smart_interact():
    from uiu.desktop_tools import dispatch_tool

    mock_res = {"success": True, "tier_used": "uia", "x": 100, "y": 200}
    with patch("uiu.smart_interact.smart_interact", return_value=mock_res):
        out = dispatch_tool("smart_interact", {"target": "确定", "action": "click"})
        data = json.loads(out)
        assert data["success"] is True
        assert data["tier_used"] == "uia"


def test_gui_action_pipeline_smart_interact_step():
    from uiu.fast_pipeline import gui_action_pipeline

    steps = [
        {"action": "smart_interact", "target": "保存"},
    ]
    mock_res = {"success": True, "tier_used": "uia", "x": 120, "y": 240}
    with patch("uiu.smart_interact.smart_interact", return_value=mock_res):
        report = gui_action_pipeline(steps)
        assert "Step 1 [smart_interact]" in report
        assert "智能交互成功" in report
