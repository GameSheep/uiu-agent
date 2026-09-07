"""Universal Pure Icon Locator — OpenCV Contour Analysis & Multi-Scale Edge Template Matching.

Handles icon-only UI elements with no text and no hover tooltips:
1. detect_icon_regions: extracts square-like clickable icon bounding boxes via OpenCV RETR_TREE + NMS.
2. find_icons_relative_to_anchor: finds icons positioned relative to a text anchor (e.g. to the right of 'Zhipu GLM').
3. match_icon_template: multi-scale edge-based template matching invariant to light/dark themes and DPI scaling.
4. annotate_set_of_marks: Set-of-Marks (SoM) visual annotation with numbered badge markers.
"""

from __future__ import annotations

import math
from typing import Any
import cv2
import numpy as np


def _to_cv2_bgr(image_or_region: Any) -> tuple[np.ndarray, tuple[int, int]]:
    """Convert PIL image, numpy array, or screen region tuple to (cv2_bgr_img, (offset_x, offset_y))."""
    offset_x, offset_y = 0, 0
    if image_or_region is None or (isinstance(image_or_region, (tuple, list)) and len(image_or_region) == 4):
        import pyautogui
        reg = tuple(image_or_region) if image_or_region else None
        if reg:
            offset_x, offset_y = int(reg[0]), int(reg[1])
        pil_img = pyautogui.screenshot(region=reg)
        img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return img, (offset_x, offset_y)

    if isinstance(image_or_region, np.ndarray):
        if len(image_or_region.shape) == 2:
            img = cv2.cvtColor(image_or_region, cv2.COLOR_GRAY2BGR)
        elif image_or_region.shape[2] == 4:
            img = cv2.cvtColor(image_or_region, cv2.COLOR_RGBA2BGR)
        else:
            img = image_or_region
        return img, (0, 0)

    # PIL Image
    if hasattr(image_or_region, "convert"):
        img = cv2.cvtColor(np.array(image_or_region.convert("RGB")), cv2.COLOR_RGB2BGR)
        return img, (0, 0)

    raise ValueError(f"Unsupported image format: {type(image_or_region)}")


def nms_boxes(boxes: list[dict[str, Any]], overlap_thresh: float = 0.35) -> list[dict[str, Any]]:
    """Non-Maximum Suppression to deduplicate overlapping detected icon bounding boxes."""
    if not boxes:
        return []
    # Sort by area descending
    sorted_boxes = sorted(boxes, key=lambda b: b["w"] * b["h"], reverse=True)
    picked = []

    for b in sorted_boxes:
        x, y, w, h = b["x"], b["y"], b["w"], b["h"]
        overlap = False
        for p in picked:
            px, py, pw, ph = p["x"], p["y"], p["w"], p["h"]
            ix1 = max(x, px)
            iy1 = max(y, py)
            ix2 = min(x + w, px + pw)
            iy2 = min(y + h, py + ph)
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2 - ix1) * (iy2 - iy1)
                union = w * h + pw * ph - inter
                if union > 0 and (inter / union) > overlap_thresh:
                    overlap = True
                    break
        if not overlap:
            picked.append(b)

    # Return sorted by x ascending, then y
    return sorted(picked, key=lambda b: (b["y"], b["x"]))


def detect_icon_regions(
    image_or_region: Any = None,
    min_size: int = 14,
    max_size: int = 56,
    aspect_ratio_range: tuple[float, float] = (0.5, 2.0),
    canny_thresh: tuple[int, int] = (30, 110),
) -> list[dict[str, Any]]:
    """Detect all small, square-like clickable icon button candidates in an image or screen region.

    Returns list of dicts with keys: 'x', 'y', 'w', 'h', 'cx', 'cy' (absolute coordinates).
    """
    img, (off_x, off_y) = _to_cv2_bgr(image_or_region)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Multi-threshold edge detection
    edges = cv2.Canny(gray, canny_thresh[0], canny_thresh[1])
    # Slight dilation to connect broken icon contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    dilated = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []

    min_ar, max_ar = aspect_ratio_range
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if min_size <= w <= max_size and min_size <= h <= max_size:
            aspect = w / float(h)
            if min_ar <= aspect <= max_ar:
                candidates.append({
                    "x": x + off_x,
                    "y": y + off_y,
                    "w": w,
                    "h": h,
                    "cx": x + off_x + w / 2.0,
                    "cy": y + off_y + h / 2.0,
                })

    return nms_boxes(candidates)


def find_icons_relative_to_anchor(
    anchor_text: str,
    direction: str = "right",
    index: int = 1,
    region: tuple[int, int, int, int] | None = None,
    max_distance: int = 700,
    engine: str = "auto",
) -> dict[str, Any] | None:
    """Locate icon buttons positioned relative to a text anchor.

    Example:
        find_icons_relative_to_anchor('Zhipu GLM', direction='right', index=2)
        -> returns the 2nd icon button to the right of 'Zhipu GLM' (e.g. Edit pencil).
    """
    from .vision_locator import locate_text_on_screen
    import pyautogui

    anchor = locate_text_on_screen(anchor_text, region=region, engine=engine)
    if not anchor:
        return None

    ax, ay, aw, ah = int(anchor["x"]), int(anchor["y"]), int(anchor["w"]), int(anchor["h"])
    acx, acy = int(round(anchor["cx"])), int(round(anchor["cy"]))

    sw, sh = pyautogui.size()
    if region:
        bounds_l, bounds_t, bounds_w, bounds_h = region
        bounds_r, bounds_b = bounds_l + bounds_w, bounds_t + bounds_h
    else:
        bounds_l, bounds_t, bounds_r, bounds_b = 0, 0, sw, sh

    direction = direction.lower().strip()
    # Define vertical row thickness around anchor
    row_margin = max(24, int(ah * 1.2))

    if direction == "right":
        zone_l = ax + aw
        zone_t = max(bounds_t, acy - row_margin)
        zone_r = min(bounds_r, zone_l + max_distance)
        zone_b = min(bounds_b, acy + row_margin)
    elif direction == "left":
        zone_r = ax
        zone_l = max(bounds_l, zone_r - max_distance)
        zone_t = max(bounds_t, acy - row_margin)
        zone_b = min(bounds_b, acy + row_margin)
    elif direction == "below":
        col_margin = max(30, int(aw * 0.8))
        zone_l = max(bounds_l, acx - col_margin)
        zone_r = min(bounds_r, acx + col_margin)
        zone_t = ay + ah
        zone_b = min(bounds_b, zone_t + max_distance)
    elif direction == "above":
        col_margin = max(30, int(aw * 0.8))
        zone_l = max(bounds_l, acx - col_margin)
        zone_r = min(bounds_r, acx + col_margin)
        zone_b = ay
        zone_t = max(bounds_t, zone_b - max_distance)
    else:
        zone_l, zone_t, zone_r, zone_b = bounds_l, bounds_t, bounds_r, bounds_b

    zw = zone_r - zone_l
    zh = zone_b - zone_t
    if zw <= 10 or zh <= 10:
        return None

    # Detect icon boxes in this relative zone
    zone_tuple = (zone_l, zone_t, zw, zh)
    boxes = detect_icon_regions(zone_tuple)
    if not boxes:
        return None

    # Sort boxes along the primary direction axis
    if direction in ("right", "left"):
        boxes.sort(key=lambda b: b["cx"] if direction == "right" else -b["cx"])
    else:
        boxes.sort(key=lambda b: b["cy"] if direction == "below" else -b["cy"])

    # If index is 1-based and within bounds
    target_idx = index - 1 if index > 0 else 0
    if 0 <= target_idx < len(boxes):
        picked = boxes[target_idx]
        picked["total_found"] = len(boxes)
        picked["index"] = index
        picked["anchor"] = anchor_text
        return picked

    return None


# ---------- Built-in Universal Icon Geometric Templates ----------

def _generate_builtin_template(name: str, size: int = 24) -> np.ndarray:
    """Generate a clean binary edge template for standard universal icons."""
    tpl = np.zeros((size, size), dtype=np.uint8)
    pad = int(size * 0.2)
    s_end = size - pad

    name_clean = name.lower().replace("_", "").replace("-", "")

    if name_clean in ("pencil", "edit"):
        # Diagonal pen line with tip
        cv2.line(tpl, (pad, s_end), (s_end, pad), 255, 2)
        cv2.line(tpl, (pad, s_end), (pad + 4, s_end), 255, 1)
        cv2.line(tpl, (pad, s_end), (pad, s_end - 4), 255, 1)

    elif name_clean in ("close", "x", "cancel"):
        # 'X' cross
        cv2.line(tpl, (pad, pad), (s_end, s_end), 255, 2)
        cv2.line(tpl, (s_end, pad), (pad, s_end), 255, 2)

    elif name_clean in ("plus", "add"):
        # '+' cross
        mid = size // 2
        cv2.line(tpl, (mid, pad), (mid, s_end), 255, 2)
        cv2.line(tpl, (pad, mid), (s_end, mid), 255, 2)

    elif name_clean in ("copy", "duplicate"):
        # Two overlapping rects
        cv2.rectangle(tpl, (pad, pad), (s_end - 4, s_end - 4), 255, 1)
        cv2.rectangle(tpl, (pad + 4, pad + 4), (s_end, s_end), 255, 1)

    elif name_clean in ("trash", "delete"):
        # Trash bin with lid
        cv2.line(tpl, (pad - 2, pad + 3), (s_end + 2, pad + 3), 255, 2)
        cv2.rectangle(tpl, (pad + 1, pad + 5), (s_end - 1, s_end), 255, 1)

    elif name_clean in ("search", "find"):
        # Magnifying glass
        r = int(size * 0.25)
        cx, cy = int(size * 0.42), int(size * 0.42)
        cv2.circle(tpl, (cx, cy), r, 255, 1)
        cv2.line(tpl, (cx + int(r * 0.7), cy + int(r * 0.7)), (s_end, s_end), 255, 2)

    elif name_clean in ("play", "run"):
        # Right-pointing triangle
        pts = np.array([[pad, pad], [s_end, size // 2], [pad, s_end]], np.int32)
        cv2.polylines(tpl, [pts], isClosed=True, color=255, thickness=2)

    elif name_clean in ("refresh", "reload"):
        # Arc with arrow
        mid = size // 2
        r = int(size * 0.32)
        cv2.ellipse(tpl, (mid, mid), (r, r), 0, 45, 315, 255, 2)
        cv2.line(tpl, (mid + r, mid), (mid + r - 3, mid - 4), 255, 2)

    elif name_clean in ("gear", "settings"):
        # Circle with gear teeth
        mid = size // 2
        r = int(size * 0.28)
        cv2.circle(tpl, (mid, mid), r, 255, 2)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = int(mid + (r - 2) * math.cos(rad))
            y1 = int(mid + (r - 2) * math.sin(rad))
            x2 = int(mid + (r + 4) * math.cos(rad))
            y2 = int(mid + (r + 4) * math.sin(rad))
            cv2.line(tpl, (x1, y1), (x2, y2), 255, 2)
    else:
        # Default square box
        cv2.rectangle(tpl, (pad, pad), (s_end, s_end), 255, 2)

    return tpl


def match_icon_template(
    icon_name_or_template: str | np.ndarray,
    region: tuple[int, int, int, int] | None = None,
    scales: tuple[float, ...] = (0.8, 0.9, 1.0, 1.15, 1.3, 1.5),
    threshold: float = 0.65,
    base_template_size: int = 24,
) -> dict[str, Any] | None:
    """Multi-scale edge-based template matching invariant to light/dark themes and DPI scaling.

    icon_name_or_template: standard name ('pencil', 'close', 'gear', 'trash', 'copy', etc.)
                           or a custom grayscale/BGR template numpy array.
    """
    if isinstance(icon_name_or_template, str):
        tpl_edges = _generate_builtin_template(icon_name_or_template, size=base_template_size)
    elif isinstance(icon_name_or_template, np.ndarray):
        gray_tpl = icon_name_or_template if len(icon_name_or_template.shape) == 2 else cv2.cvtColor(icon_name_or_template, cv2.COLOR_BGR2GRAY)
        tpl_edges = cv2.Canny(gray_tpl, 40, 120)
    else:
        raise ValueError(f"Invalid template: {type(icon_name_or_template)}")

    scene_img, (off_x, off_y) = _to_cv2_bgr(region)
    scene_gray = cv2.cvtColor(scene_img, cv2.COLOR_BGR2GRAY)
    scene_edges = cv2.Canny(scene_gray, 40, 120)

    best_match = None
    best_val = -1.0

    scene_h, scene_w = scene_edges.shape

    for scale in scales:
        th = int(tpl_edges.shape[0] * scale)
        tw = int(tpl_edges.shape[1] * scale)
        if th >= scene_h or tw >= scene_w or th < 10 or tw < 10:
            continue

        scaled_tpl = cv2.resize(tpl_edges, (tw, th), interpolation=cv2.INTER_LINEAR)
        res = cv2.matchTemplate(scene_edges, scaled_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val > best_val:
            best_val = float(max_val)
            lx, ly = max_loc
            best_match = {
                "x": lx + off_x,
                "y": ly + off_y,
                "w": tw,
                "h": th,
                "cx": lx + off_x + tw / 2.0,
                "cy": ly + off_y + th / 2.0,
                "score": round(best_val, 3),
                "scale": scale,
                "template": icon_name_or_template if isinstance(icon_name_or_template, str) else "custom",
            }

    if best_match and best_val >= threshold:
        return best_match

    return None


def annotate_set_of_marks(
    image_or_region: Any = None,
    boxes: list[dict[str, Any]] | None = None,
) -> np.ndarray:
    """Draw numbered badges [1], [2], [3] over detected boxes (Set-of-Marks, SoM)."""
    img, _ = _to_cv2_bgr(image_or_region)
    annotated = img.copy()

    if boxes is None:
        boxes = detect_icon_regions(img)

    for i, b in enumerate(boxes, 1):
        x, y, w, h = int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"])
        # Draw bounding rect
        cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 140, 255), 2)
        # Draw label badge
        label = f"[{i}]"
        badge_w, badge_h = 24, 18
        bx1 = max(0, x - 2)
        by1 = max(0, y - badge_h - 2)
        cv2.rectangle(annotated, (bx1, by1), (bx1 + badge_w, by1 + badge_h), (0, 140, 255), -1)
        cv2.putText(annotated, str(i), (bx1 + 5, by1 + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    return annotated
