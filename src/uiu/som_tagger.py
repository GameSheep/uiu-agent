"""Set-of-Mark (SoM) Visual Grounding & Interactive Grid Tagging Engine.

Inspired by Microsoft UFO, UI-TARS, OmniParser, and Appium.
Overlays high-contrast numbered badges ([1], [2], [3]...) over interactive UI elements.
Enables 100% deterministic, coordinate-hallucination-free interaction for Multimodal LLMs & Agents.
"""

from __future__ import annotations

import base64
import io
import json
import threading
from dataclasses import asdict, dataclass
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFont


@dataclass
class SoMElement:
    tag_id: int
    text: str
    control_type: str
    box: list[int]  # [x, y, w, h]
    center: list[int]  # [cx, cy]
    source: str  # "uia" | "ocr"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Thread-safe storage of the most recent Set-of-Mark catalog
_CATALOG_LOCK = threading.Lock()
LAST_SOM_CATALOG: dict[str, SoMElement] = {}


def _calculate_iou(box1: list[int], box2: list[int]) -> float:
    """Calculate Intersection over Union (IoU) of two [x, y, w, h] boxes."""
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2

    xi1 = max(x1, x2)
    yi1 = max(y1, y2)
    xi2 = min(x1 + w1, x2 + w2)
    yi2 = min(y1 + h1, y2 + h2)

    inter_w = max(0, xi2 - xi1)
    inter_h = max(0, yi2 - yi1)
    inter_area = inter_w * inter_h

    area1 = w1 * h1
    area2 = w2 * h2
    union_area = area1 + area2 - inter_area

    return float(inter_area) / float(union_area) if union_area > 0 else 0.0


def detect_interactive_elements(
    region: tuple[int, int, int, int] | None = None,
    window_title: str | None = None,
    max_elements: int = 50,
) -> list[SoMElement]:
    """Scan and merge UIA interactive controls and OCR text blocks into a non-overlapping catalog."""
    from .screen_tools import safe_screenshot
    from .uia_locator import list_uia_controls
    from .vision_locator import get_screen_elements

    candidates: list[dict[str, Any]] = []

    # 1. Harvest UIA controls (fastest, semantic control types)
    try:
        uia_nodes = list_uia_controls(window_title=window_title, max_count=max_elements)
        for u in uia_nodes:
            rect = u.get("rect", [0, 0, 0, 0])
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            if 8 <= w <= 800 and 8 <= h <= 400:
                candidates.append({
                    "text": u.get("name") or "",
                    "control_type": u.get("control_type", "Control"),
                    "box": [rect[0], rect[1], w, h],
                    "cx": rect[0] + w // 2,
                    "cy": rect[1] + h // 2,
                    "source": "uia",
                })
    except Exception:
        pass

    # 2. Harvest OCR blocks (captures text buttons, web links, custom rendered UI)
    try:
        ocr_nodes = get_screen_elements(region=region)
        for o in ocr_nodes:
            w = int(o.get("w", 0))
            h = int(o.get("h", 0))
            text = str(o.get("text", "")).strip()
            if 6 <= w <= 800 and 6 <= h <= 300 and text:
                candidates.append({
                    "text": text,
                    "control_type": "TextBlock",
                    "box": [int(o.get("x", 0)), int(o.get("y", 0)), w, h],
                    "cx": int(o.get("cx", o.get("x", 0) + w // 2)),
                    "cy": int(o.get("cy", o.get("y", 0) + h // 2)),
                    "source": "ocr",
                })
    except Exception:
        pass

    # 3. Non-maximum suppression / deduplication
    deduped: list[dict[str, Any]] = []
    for cand in candidates:
        cand_box = cand["box"]
        overlap = False
        for existing in deduped:
            iou = _calculate_iou(cand_box, existing["box"])
            # Center proximity check (< 12px)
            dist = abs(cand["cx"] - existing["cx"]) + abs(cand["cy"] - existing["cy"])
            if iou > 0.4 or dist < 12:
                # Merge text if existing is missing text
                if not existing["text"] and cand["text"]:
                    existing["text"] = cand["text"]
                overlap = True
                break
        if not overlap:
            deduped.append(cand)
            if len(deduped) >= max_elements:
                break

    # Sort elements in natural reading order (top-to-bottom, left-to-right)
    deduped.sort(key=lambda item: (item["box"][1] // 25, item["box"][0]))

    # Assign sequential 1-based tag IDs
    som_elements: list[SoMElement] = []
    for idx, d in enumerate(deduped, start=1):
        som_elements.append(SoMElement(
            tag_id=idx,
            text=d["text"],
            control_type=d["control_type"],
            box=d["box"],
            center=[d["cx"], d["cy"]],
            source=d["source"],
        ))

    return som_elements


def render_som_tags(
    image: Image.Image | None = None,
    elements: list[SoMElement] | None = None,
    region: tuple[int, int, int, int] | None = None,
    save_path: str | None = None,
) -> tuple[Image.Image, dict[str, SoMElement]]:
    """Draw vibrant Set-of-Mark tags and bounding boxes on the image."""
    from .screen_tools import safe_screenshot

    if image is None:
        image = safe_screenshot(region=region)
    else:
        image = image.copy()

    if elements is None:
        elements = detect_interactive_elements(region=region)

    draw = ImageDraw.Draw(image)
    catalog: dict[str, SoMElement] = {}

    # High-contrast color palette for SoM tags
    BOX_COLOR = (224, 36, 195)      # Vibrant Magenta
    TAG_BG_COLOR = (224, 36, 195)   # Tag pill background
    TAG_TEXT_COLOR = (255, 255, 255) # Pure White text

    # Try loading a readable system font, fallback to default bitmap font
    font = None
    for font_name in ["arial.ttf", "msyh.ttc", "seguiemj.ttf"]:
        try:
            font = ImageFont.truetype(font_name, 12)
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()

    reg_offset_x = region[0] if region else 0
    reg_offset_y = region[1] if region else 0

    for elem in elements:
        x, y, w, h = elem.box
        # Normalize relative to screenshot region if needed
        rel_x = x - reg_offset_x
        rel_y = y - reg_offset_y

        if rel_x < 0 or rel_y < 0 or rel_x >= image.width or rel_y >= image.height:
            continue

        tag_str = str(elem.tag_id)
        catalog[tag_str] = elem

        # 1. Draw outer boundary box
        draw.rectangle([rel_x, rel_y, rel_x + w, rel_y + h], outline=BOX_COLOR, width=2)

        # 2. Draw numbered pill badge at top-left
        badge_w = 14 + len(tag_str) * 7
        badge_h = 16
        badge_x1 = max(0, rel_x)
        badge_y1 = max(0, rel_y - badge_h)
        badge_x2 = badge_x1 + badge_w
        badge_y2 = badge_y1 + badge_h

        draw.rectangle([badge_x1, badge_y1, badge_x2, badge_y2], fill=TAG_BG_COLOR)
        draw.text((badge_x1 + 3, badge_y1 + 1), tag_str, fill=TAG_TEXT_COLOR, font=font)

    # Cache globally
    global LAST_SOM_CATALOG
    with _CATALOG_LOCK:
        LAST_SOM_CATALOG = catalog

    if save_path:
        image.save(save_path)

    return image, catalog


def click_som_tag(
    tag_id: int | str,
    action: Literal["click", "double_click", "right_click", "hover"] = "click",
    verify_change: bool = True,
) -> str:
    """Execute action by referencing an active Set-of-Mark tag ID."""
    global LAST_SOM_CATALOG
    with _CATALOG_LOCK:
        elem = LAST_SOM_CATALOG.get(str(tag_id))

    if not elem:
        return f"[error] 未找到编号为 [{tag_id}] 的标记元素。请先调用 visual_tag_screen 刷新标记。"

    from .dpi_manager import calculate_safe_target, physical_to_logical
    from .gui_primitives import mouse_click, mouse_move
    from .screen_diff import verify_action_visual_effect

    # Target calculation with optical safe centering
    tx, ty = calculate_safe_target(elem.box, strategy="safe_center")
    log_x, log_y = physical_to_logical(tx, ty)

    def _do_action():
        if action == "hover":
            return mouse_move(log_x, log_y)
        elif action == "double_click":
            return mouse_click(log_x, log_y, clicks=2)
        elif action == "right_click":
            return mouse_click(log_x, log_y, button="right")
        else:
            return mouse_click(log_x, log_y, button="left")

    if verify_change:
        res_text, diff = verify_action_visual_effect(
            _do_action,
            region=tuple(elem.box),
            settle_ms=250.0,
        )
        changed = diff.get("has_changed", False)
        return (
            f"[ok] 已在元素 [{tag_id}] ('{elem.text}') 执行 {action}。\n"
            f"目标位置: ({log_x}, {log_y}), 视觉变动检测: {'有效更新' if changed else '无明显变动'}"
        )
    else:
        res_text = _do_action()
        return f"[ok] 已在元素 [{tag_id}] ('{elem.text}') 执行 {action}: {res_text}"


def capture_and_tag_screen(
    region: list[int] | None = None,
    window_title: str | None = None,
    max_elements: int = 40,
) -> str:
    """Full pipeline: capture, detect, render Set-of-Mark tags, and return markdown element directory."""
    r_tuple = tuple(region) if region and len(region) == 4 else None
    elements = detect_interactive_elements(region=r_tuple, window_title=window_title, max_elements=max_elements)
    _, catalog = render_som_tags(elements=elements, region=r_tuple)

    if not catalog:
        return "[warning] 当前视口内未检测到显著的可交互控件或文本元素。"

    # Build concise markdown directory of clickable elements
    lines = [f"### [Set-of-Mark 视口标记目录 (共 {len(catalog)} 项)]", "| Tag | 类型 | 控件/文本内容 | 坐标 (cx, cy) |", "| :---: | :---: | :--- | :---: |"]
    for tag_str, el in catalog.items():
        desc = el.text.replace("\n", " ").strip()
        if not desc:
            desc = f"<{el.control_type}>"
        if len(desc) > 30:
            desc = desc[:28] + ".."
        lines.append(f"| **[{tag_str}]** | {el.control_type} | {desc} | ({el.center[0]}, {el.center[1]}) |")

    lines.append("\n**使用指引**: 直接调用 `som_click_tag(tag=N)` 即可 100% 确定性点击对应标记。")
    return "\n".join(lines)
