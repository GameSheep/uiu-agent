"""Spatial Anchor & Topological Relational Locator Engine.

Resolves ambiguous UI elements by spatial relationship to an anchor element.
Solves scenarios like:
- "Click the 'Edit' button to the RIGHT of 'Zhipu GLM'"
- "Click the input field BELOW 'Username'"
- "Click the eye icon INSIDE the password box"
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class BoundingBox:
    left: int
    top: int
    width: int
    height: int
    text: str = ""
    control_type: str = ""

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def cx(self) -> int:
        return self.left + self.width // 2

    @property
    def cy(self) -> int:
        return self.top + self.height // 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "box": [self.left, self.top, self.width, self.height],
            "cx": self.cx,
            "cy": self.cy,
            "text": self.text,
            "control_type": self.control_type,
        }


def _collect_screen_boxes(
    region: tuple[int, int, int, int] | None = None,
    window_title: str | None = None,
) -> list[BoundingBox]:
    """Collect all visible UI elements from OCR and UIA."""
    from .uia_locator import list_uia_controls
    from .vision_locator import get_screen_elements

    boxes: list[BoundingBox] = []

    # 1. OCR elements
    try:
        ocr_items = get_screen_elements(region=region)
        for it in ocr_items:
            w = int(it.get("w", 0))
            h = int(it.get("h", 0))
            text = str(it.get("text", "")).strip()
            if w > 0 and h > 0 and text:
                boxes.append(BoundingBox(
                    left=int(it.get("x", 0)),
                    top=int(it.get("y", 0)),
                    width=w,
                    height=h,
                    text=text,
                    control_type="OCRText",
                ))
    except Exception:
        pass

    # 2. UIA elements
    try:
        uia_items = list_uia_controls(window_title=window_title, max_count=60)
        for u in uia_items:
            rect = u.get("rect", [0, 0, 0, 0])
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if w > 0 and h > 0:
                boxes.append(BoundingBox(
                    left=rect[0],
                    top=rect[1],
                    width=w,
                    height=h,
                    text=u.get("name", ""),
                    control_type=u.get("control_type", "Control"),
                ))
    except Exception:
        pass

    return boxes


def match_spatial_relation(
    anchor_box: BoundingBox,
    candidate_box: BoundingBox,
    relation: Literal["right", "left", "below", "above", "inside"],
    max_distance_px: float = 400.0,
) -> float | None:
    """Calculate distance score if candidate satisfies spatial relation to anchor.
    Returns Euclidean distance if matched, or None if candidate violates directional constraint.
    """
    ax, ay, aw, ah = anchor_box.left, anchor_box.top, anchor_box.width, anchor_box.height
    cx, cy, cw, ch = candidate_box.left, candidate_box.top, candidate_box.width, candidate_box.height

    if relation == "right":
        # Must be to the right of anchor
        if cx < anchor_box.right - 8:
            return None
        # Must have vertical overlap or near-horizontal row alignment
        v_overlap = min(anchor_box.bottom, candidate_box.bottom) - max(ay, cy)
        v_dist = abs(anchor_box.cy - candidate_box.cy)
        max_v_allow = max(ah, ch, 35) * 1.6
        if v_overlap <= 0 and v_dist > max_v_allow:
            return None
        dx = cx - anchor_box.right
        dy = anchor_box.cy - candidate_box.cy
        dist = math.hypot(max(0, dx), dy)
        return dist if dist <= max_distance_px else None

    elif relation == "left":
        # Must be to the left of anchor
        if candidate_box.right > ax + 8:
            return None
        v_overlap = min(anchor_box.bottom, candidate_box.bottom) - max(ay, cy)
        v_dist = abs(anchor_box.cy - candidate_box.cy)
        max_v_allow = max(ah, ch, 35) * 1.6
        if v_overlap <= 0 and v_dist > max_v_allow:
            return None
        dx = ax - candidate_box.right
        dy = anchor_box.cy - candidate_box.cy
        dist = math.hypot(max(0, dx), dy)
        return dist if dist <= max_distance_px else None

    elif relation == "below":
        # Must be below anchor
        if cy < anchor_box.bottom - 8:
            return None
        h_overlap = min(anchor_box.right, candidate_box.right) - max(ax, cx)
        h_dist = abs(anchor_box.cx - candidate_box.cx)
        max_h_allow = max(aw, cw, 40) * 1.8
        if h_overlap <= 0 and h_dist > max_h_allow:
            return None
        dy = cy - anchor_box.bottom
        dx = anchor_box.cx - candidate_box.cx
        dist = math.hypot(dx, max(0, dy))
        return dist if dist <= max_distance_px else None

    elif relation == "above":
        # Must be above anchor
        if candidate_box.bottom > ay + 8:
            return None
        h_overlap = min(anchor_box.right, candidate_box.right) - max(ax, cx)
        h_dist = abs(anchor_box.cx - candidate_box.cx)
        max_h_allow = max(aw, cw, 40) * 1.8
        if h_overlap <= 0 and h_dist > max_h_allow:
            return None
        dy = ay - candidate_box.bottom
        dx = anchor_box.cx - candidate_box.cx
        dist = math.hypot(dx, max(0, dy))
        return dist if dist <= max_distance_px else None

    elif relation == "inside":
        # Candidate must be inside anchor bounding box
        if (cx >= ax - 4 and cy >= ay - 4 and
            candidate_box.right <= anchor_box.right + 4 and
            candidate_box.bottom <= anchor_box.bottom + 4):
            return 0.0
        return None

    return None


def find_element_by_relation(
    target: str,
    anchor: str,
    relation: Literal["right", "left", "below", "above", "inside"] = "right",
    max_distance_px: float = 400.0,
    region: tuple[int, int, int, int] | None = None,
    window_title: str | None = None,
) -> dict[str, Any] | None:
    """Find a target UI element by its spatial relation to an anchor element."""
    boxes = _collect_screen_boxes(region=region, window_title=window_title)
    if not boxes:
        return None

    anchor_norm = anchor.strip().lower()
    target_norm = target.strip().lower()

    # 1. Locate anchor candidates
    anchors = [b for b in boxes if anchor_norm in b.text.lower()]
    if not anchors:
        return None

    # 2. Locate target candidates
    # If target is empty or generic, treat any interactive box as candidate
    if not target_norm or target_norm in ("元素", "控件", "按钮", "button", "input", "输入框"):
        targets = [b for b in boxes if b not in anchors]
    else:
        targets = [b for b in boxes if target_norm in b.text.lower() and b not in anchors]
        if not targets:
            # Fallback: allow partial match
            targets = [b for b in boxes if any(ch in b.text.lower() for ch in target_norm) and b not in anchors]

    if not targets:
        return None

    # 3. Find closest target satisfying relation across all matching anchors
    best_candidate: BoundingBox | None = None
    min_dist: float = float("inf")
    matched_anchor: BoundingBox | None = None

    for anc in anchors:
        for cand in targets:
            dist = match_spatial_relation(anc, cand, relation=relation, max_distance_px=max_distance_px)
            if dist is not None and dist < min_dist:
                min_dist = dist
                best_candidate = cand
                matched_anchor = anc

    if best_candidate and matched_anchor:
        res = best_candidate.to_dict()
        res["distance"] = round(min_dist, 1)
        res["anchor"] = matched_anchor.to_dict()
        res["relation"] = relation
        return res

    return None
