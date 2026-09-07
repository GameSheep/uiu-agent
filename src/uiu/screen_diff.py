"""Screen Visual Diffing & Action Feedback Engine — Anthropic Computer Use / OSWorld Pattern.

Provides real-time, sub-millisecond visual delta detection:
- Verifies whether GUI clicks, hotkeys, or scrolls actually triggered visual transitions.
- Identifies the bounding boxes of UI elements that appeared, disappeared, or changed.
- 100% in-memory with zero disk footprint.
"""

from __future__ import annotations

import time
from typing import Any, Callable
import cv2
import numpy as np


def _to_gray_array(img_or_region: Any) -> np.ndarray:
    """Convert input image (PIL Image, numpy array, or screen region) into a grayscale ndarray."""
    if img_or_region is None or (isinstance(img_or_region, (tuple, list)) and len(img_or_region) == 4):
        from .screen_tools import safe_screenshot
        reg = tuple(img_or_region) if img_or_region else None
        pil_img = safe_screenshot(region=reg)
        arr = np.array(pil_img)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


    if isinstance(img_or_region, np.ndarray):
        if len(img_or_region.shape) == 3:
            return cv2.cvtColor(img_or_region, cv2.COLOR_BGR2GRAY)
        return img_or_region

    if hasattr(img_or_region, "convert"):
        return np.array(img_or_region.convert("L"))

    raise ValueError(f"Unsupported image type: {type(img_or_region)}")


def compute_screen_diff(
    before: Any,
    after: Any,
    region_offset: tuple[int, int] = (0, 0),
    pixel_threshold: int = 25,
    min_box_area: int = 20,
) -> dict[str, Any]:
    """Compute visual delta between two screen frames.

    Returns:
        {
            'has_changed': bool,
            'change_ratio': float (0.0 to 1.0),
            'changed_pixels': int,
            'total_pixels': int,
            'diff_score': float (MSE),
            'changed_boxes': [{'x', 'y', 'w', 'h', 'area'}, ...]
        }
    """
    g_before = _to_gray_array(before)
    g_after = _to_gray_array(after)

    # Ensure identical dimensions
    if g_before.shape != g_after.shape:
        # Resize after to match before if screen size changed
        g_after = cv2.resize(g_after, (g_before.shape[1], g_before.shape[0]))

    h, w = g_before.shape
    total_pixels = h * w
    if total_pixels == 0:
        return {
            "has_changed": False,
            "change_ratio": 0.0,
            "changed_pixels": 0,
            "total_pixels": 0,
            "diff_score": 0.0,
            "changed_boxes": [],
        }

    # Absolute difference
    diff = cv2.absdiff(g_before, g_after)
    mse = float(np.mean(diff.astype(np.float32) ** 2))

    # Binary threshold for changed pixels
    _, thresh = cv2.threshold(diff, pixel_threshold, 255, cv2.THRESH_BINARY)
    changed_pixels = int(np.count_nonzero(thresh))
    change_ratio = float(changed_pixels) / float(total_pixels)

    # Morphological opening to remove isolated noise speckles
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    clean_thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    # Find bounding boxes of changed visual components
    contours, _ = cv2.findContours(clean_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    ox, oy = region_offset
    boxes = []

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area >= min_box_area:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            boxes.append({
                "x": bx + ox,
                "y": by + oy,
                "w": bw,
                "h": bh,
                "area": int(area),
            })

    # Sort boxes by area descending
    boxes.sort(key=lambda b: b["area"], reverse=True)

    has_changed = change_ratio >= 0.0001 or len(boxes) > 0

    return {
        "has_changed": has_changed,
        "change_ratio": round(change_ratio, 5),
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
        "diff_score": round(mse, 2),
        "changed_boxes": boxes[:10],
    }


def verify_action_effect(
    action_fn: Callable[[], Any],
    region: tuple[int, int, int, int] | None = None,
    settle_ms: float = 120.0,
    pixel_threshold: int = 25,
) -> tuple[Any, dict[str, Any]]:
    """Execute action_fn and verify if it triggered any visible GUI state change.

    Returns (action_result, diff_info).
    """
    from .screen_tools import safe_screenshot

    before_shot = safe_screenshot(region=region)

    result = action_fn()

    if settle_ms > 0:
        time.sleep(settle_ms / 1000.0)

    after_shot = safe_screenshot(region=region)

    offset = (region[0], region[1]) if region else (0, 0)
    diff = compute_screen_diff(before_shot, after_shot, region_offset=offset, pixel_threshold=pixel_threshold)

    return result, diff
