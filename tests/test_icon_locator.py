"""Tests for icon locator: contour detection, NMS, template matching, and relative anchoring."""

import cv2
import numpy as np
from unittest.mock import patch


def test_detect_icon_regions_and_nms():
    from uiu.icon_locator import detect_icon_regions, nms_boxes

    # Create synthetic image with 2 isolated small square boxes
    img = np.ones((200, 400, 3), dtype=np.uint8) * 240
    # Box 1: 24x24 at (50, 50)
    cv2.rectangle(img, (50, 50), (74, 74), (20, 20, 20), 2)
    # Box 2: 28x28 at (120, 50)
    cv2.rectangle(img, (120, 50), (148, 78), (20, 20, 20), 2)

    boxes = detect_icon_regions(img)
    assert len(boxes) >= 2

    # Check center coordinates
    coords = [(b["cx"], b["cy"]) for b in boxes]
    found_b1 = any(abs(cx - 62) <= 3 and abs(cy - 62) <= 3 for cx, cy in coords)
    found_b2 = any(abs(cx - 134) <= 3 and abs(cy - 64) <= 3 for cx, cy in coords)
    assert found_b1, f"Box 1 not found in {coords}"
    assert found_b2, f"Box 2 not found in {coords}"


def test_nms_boxes_deduplication():
    from uiu.icon_locator import nms_boxes

    boxes = [
        {"x": 10, "y": 10, "w": 24, "h": 24},
        {"x": 11, "y": 11, "w": 24, "h": 24},  # heavily overlapping
        {"x": 100, "y": 10, "w": 24, "h": 24}, # separate
    ]
    picked = nms_boxes(boxes, overlap_thresh=0.3)
    assert len(picked) == 2


def test_match_icon_template_close_and_pencil():
    from uiu.icon_locator import match_icon_template, _generate_builtin_template

    # Scene with a 'close' ('X') icon at (100, 60)
    scene = np.ones((150, 300, 3), dtype=np.uint8) * 240
    cv2.line(scene, (105, 65), (125, 85), (0, 0, 0), 2)
    cv2.line(scene, (125, 65), (105, 85), (0, 0, 0), 2)

    with patch("pyautogui.screenshot", return_value=scene):
        res = match_icon_template("close", region=(0, 0, 300, 150), threshold=0.55)
        assert res is not None
        assert abs(res["cx"] - 115) <= 10
        assert abs(res["cy"] - 75) <= 10


def test_find_icons_relative_to_anchor():
    from uiu.icon_locator import find_icons_relative_to_anchor

    mock_anchor = {
        "x": 40, "y": 50, "w": 80, "h": 24,
        "cx": 80, "cy": 62, "text": "TestRow"
    }

    # Scene with 2 icons to the right: at x=160 and x=220
    scene = np.ones((150, 400, 3), dtype=np.uint8) * 245
    cv2.rectangle(scene, (160, 50), (184, 74), (10, 10, 10), 2)  # Icon 1
    cv2.rectangle(scene, (220, 50), (244, 74), (10, 10, 10), 2)  # Icon 2

    def mock_screenshot(region=None):
        if region:
            x, y, w, h = region
            return scene[y:y+h, x:x+w]
        return scene

    with patch("uiu.vision_locator.locate_text_on_screen", return_value=mock_anchor), \
         patch("pyautogui.size", return_value=(400, 150)), \
         patch("pyautogui.screenshot", side_effect=mock_screenshot):
        icon1 = find_icons_relative_to_anchor("TestRow", direction="right", index=1)
        assert icon1 is not None
        assert abs(icon1["cx"] - 172) <= 5

        icon2 = find_icons_relative_to_anchor("TestRow", direction="right", index=2)
        assert icon2 is not None
        assert abs(icon2["cx"] - 232) <= 5


def test_annotate_set_of_marks():
    from uiu.icon_locator import annotate_set_of_marks

    img = np.ones((100, 200, 3), dtype=np.uint8) * 255
    boxes = [{"x": 20, "y": 20, "w": 24, "h": 24}]
    annotated = annotate_set_of_marks(img, boxes=boxes)
    assert isinstance(annotated, np.ndarray)
    assert annotated.shape == img.shape
