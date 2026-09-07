"""Tests for visual screen diffing engine (OSWorld / Anthropic Computer Use pattern)."""

import cv2
import numpy as np
from unittest.mock import patch


def test_compute_screen_diff_identical():
    from uiu.screen_diff import compute_screen_diff

    img = np.ones((100, 200), dtype=np.uint8) * 128
    res = compute_screen_diff(img, img)
    assert res["has_changed"] is False
    assert res["change_ratio"] == 0.0
    assert res["changed_pixels"] == 0
    assert len(res["changed_boxes"]) == 0


def test_compute_screen_diff_with_popup():
    from uiu.screen_diff import compute_screen_diff

    before = np.ones((200, 300), dtype=np.uint8) * 200
    after = before.copy()
    # Draw a simulated modal/dialog popup at (50, 40) with size 100x60
    cv2.rectangle(after, (50, 40), (150, 100), (30,), -1)

    res = compute_screen_diff(before, after)
    assert res["has_changed"] is True
    assert res["change_ratio"] > 0.05
    assert len(res["changed_boxes"]) >= 1

    # Check that changed box covers the modal
    box = res["changed_boxes"][0]
    assert abs(box["x"] - 50) <= 5
    assert abs(box["y"] - 40) <= 5
    assert abs(box["w"] - 100) <= 5
    assert abs(box["h"] - 60) <= 5


def test_verify_action_effect():
    from uiu.screen_diff import verify_action_effect

    before = np.ones((100, 100, 3), dtype=np.uint8) * 255
    after = before.copy()
    cv2.circle(after, (50, 50), 15, (0, 0, 0), -1)

    shots = [before, after]

    def mock_screenshot(region=None):
        return shots.pop(0)

    def dummy_action():
        return "action_ok"

    with patch("pyautogui.screenshot", side_effect=mock_screenshot), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        ret, diff = verify_action_effect(dummy_action, settle_ms=0)
        assert ret == "action_ok"
        assert diff["has_changed"] is True
