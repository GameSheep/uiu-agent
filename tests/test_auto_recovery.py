"""Tests for autonomous UI recovery and interruption handling."""

import json
import numpy as np
from unittest.mock import patch
from uiu.auto_recovery import (
    wait_screen_stable,
    detect_modal_dialog,
    dismiss_blocking_dialog,
    resilient_click,
)


def test_wait_screen_stable_immediate():
    img = np.ones((50, 50, 3), dtype=np.uint8) * 200
    with patch("pyautogui.screenshot", return_value=img):
        ok = wait_screen_stable(max_wait_ms=300.0, check_interval_ms=20.0)
        assert ok is True


def test_detect_modal_dialog_vision():
    mock_btn = {"cx": 200, "cy": 150, "text": "取消"}
    with patch("uiautomation.GetRootControl", side_effect=Exception("no uia")), \
         patch("uiu.vision_locator.locate_text_on_screen", return_value=mock_btn):
        dlg = detect_modal_dialog()
        assert dlg is not None
        assert dlg["detected"] is True
        assert dlg["cx"] == 200
        assert dlg["cy"] == 150


def test_dismiss_blocking_dialog_esc():
    with patch("uiu.auto_recovery.detect_modal_dialog", return_value=None), \
         patch("uiu.gui_primitives.press_key", return_value="[ok] 按下 esc") as mock_press:
        dismiss_blocking_dialog()
        mock_press.assert_called_with("esc")


def test_resilient_click_end_to_end():
    mock_smart = {"success": True, "tier_used": "uia", "x": 100, "y": 200, "visual_changed": True}
    with patch("uiu.auto_recovery.wait_screen_stable", return_value=True), \
         patch("uiu.auto_recovery.detect_modal_dialog", return_value=None), \
         patch("uiu.smart_interact.smart_interact", return_value=mock_smart):
        res = resilient_click("确定", wait_stable=True, auto_dismiss_popups=True)
        assert res["success"] is True
        assert res["tier_used"] == "uia"
        assert res["total_ms"] >= 0


def test_desktop_tools_resilient_dispatch():
    from uiu.desktop_tools import dispatch_tool

    mock_res = {"success": True, "tier_used": "ocr", "x": 50, "y": 60}
    with patch("uiu.auto_recovery.resilient_click", return_value=mock_res):
        out = dispatch_tool("resilient_click", {"target": "保存"})
        data = json.loads(out)
        assert data["success"] is True

    with patch("uiu.auto_recovery.wait_screen_stable", return_value=True):
        out = dispatch_tool("wait_screen_stable", {"max_wait_ms": 1000})
        data = json.loads(out)
        assert data["stable"] is True
