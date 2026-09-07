"""Smart Self-Healing Interaction Engine — Unified Multi-Modal GUI Action Primitives.

Implements an automated 4-tier fallback & self-healing strategy:
    Tier 1 (UIA Control) -> Tier 2 (OCR Text) -> Tier 3 (Anchor Relative Icon) -> Tier 4 (Icon Template)
Combined with post-action visual state delta verification (Screen Diffing) to eliminate silent failure.
"""

from __future__ import annotations

import json
from typing import Any


def smart_interact(
    target: str | dict[str, Any],
    action: str = "click",
    clicks: int = 1,
    button: str = "left",
    region: tuple[int, int, int, int] | list[int] | None = None,
    verify_change: bool = True,
    window_title: str | None = None,
    fallback_chain: list[str] | None = None,
) -> dict[str, Any]:
    """Execute unified smart interaction with automatic 4-tier fallback and visual change verification.

    target:
        - str: text or icon name, e.g. "设置", "保存", "pencil", "close"
        - dict: e.g. {"text": "Zhipu GLM", "near_icon": 2, "direction": "right"}
                or {"icon": "pencil", "region": [...]}
                or {"name": "确定", "control_type": "Button"}
    action: 'click' | 'double_click' | 'right_click' | 'hover' | 'find_only'
    """
    from .gui_primitives import mouse_click, mouse_move
    from .screen_diff import verify_action_effect

    reg_tuple = tuple(region) if region and len(region) == 4 else None
    chain = fallback_chain or ["uia", "ocr", "icon_anchor", "icon_template"]

    # Parse target properties
    target_text = ""
    target_icon = ""
    uia_name = ""
    uia_type = "Button"
    anchor_text = ""
    anchor_dir = "right"
    anchor_idx = 1

    if isinstance(target, str):
        target_clean = target.strip()
        target_text = target_clean
        uia_name = target_clean
        target_icon = target_clean
    elif isinstance(target, dict):
        target_text = target.get("text", "")
        target_icon = target.get("icon", "")
        uia_name = target.get("name", target.get("uia_name", target_text))
        uia_type = target.get("control_type", target.get("type", "Button"))
        anchor_text = target.get("anchor", target.get("anchor_text", ""))
        anchor_dir = target.get("direction", "right")
        anchor_idx = int(target.get("index", target.get("near_icon", 1)))
        if not reg_tuple and target.get("region"):
            r = target.get("region")
            if len(r) == 4:
                reg_tuple = tuple(r)
    else:
        return {"success": False, "message": f"非法目标类型: {type(target)}"}

    target_elem = None
    tier_used = None
    attempt_logs = []

    # --- Tier 1: Windows UIA ---
    if "uia" in chain and uia_name:
        from .uia_locator import find_uia_control
        try:
            elem = find_uia_control(name=uia_name, control_type=uia_type, window_title=window_title)
            if elem:
                target_elem = elem
                tier_used = "uia"
                attempt_logs.append(f"UIA 命中: '{elem.get('name')}' ({elem.get('control_type')}) at ({elem['cx']}, {elem['cy']})")
        except Exception as e:
            attempt_logs.append(f"UIA 异常: {e}")

    # --- Tier 2: OCR Text Locating ---
    if not target_elem and "ocr" in chain and target_text:
        from .vision_locator import locate_text_on_screen
        try:
            elem = locate_text_on_screen(target_text, region=reg_tuple, use_hierarchical=True)
            if elem:
                target_elem = elem
                tier_used = "ocr"
                attempt_logs.append(f"OCR 命中: '{elem.get('text')}' at ({int(round(elem['cx']))}, {int(round(elem['cy']))})")
        except Exception as e:
            attempt_logs.append(f"OCR 异常: {e}")

    # --- Tier 3: Anchor-Relative Icon Locating ---
    if not target_elem and "icon_anchor" in chain and (anchor_text or (isinstance(target, dict) and "near_icon" in target)):
        from .icon_locator import find_icons_relative_to_anchor
        try:
            a_text = anchor_text or target_text
            elem = find_icons_relative_to_anchor(a_text, direction=anchor_dir, index=anchor_idx, region=reg_tuple)
            if elem:
                target_elem = elem
                tier_used = "icon_anchor"
                attempt_logs.append(f"锚点图标命中: 在 '{a_text}' {anchor_dir} 第 {anchor_idx} 个图标 at ({int(round(elem['cx']))}, {int(round(elem['cy']))})")
        except Exception as e:
            attempt_logs.append(f"锚点图标异常: {e}")

    # --- Tier 4: Icon Template Matching ---
    if not target_elem and "icon_template" in chain and target_icon:
        from .icon_locator import match_icon_template
        try:
            elem = match_icon_template(target_icon, region=reg_tuple)
            if elem:
                target_elem = elem
                tier_used = "icon_template"
                attempt_logs.append(f"图标模板命中: '{target_icon}' at ({int(round(elem['cx']))}, {int(round(elem['cy']))}) score={elem.get('score')}")
        except Exception as e:
            attempt_logs.append(f"图标模板异常: {e}")

    if not target_elem:
        return {
            "success": False,
            "target": target,
            "message": f"在所有策略层 ({', '.join(chain)}) 中均未能定位目标",
            "attempts": attempt_logs,
        }

    cx = int(round(target_elem["cx"]))
    cy = int(round(target_elem["cy"]))

    if action == "find_only":
        return {
            "success": True,
            "target": target,
            "tier_used": tier_used,
            "x": cx,
            "y": cy,
            "detail": target_elem,
            "attempts": attempt_logs,
        }

    # Execute action
    def _do_action():
        if action == "hover":
            return mouse_move(cx, cy, duration=0.05)
        elif action in ("double_click", "dblclick"):
            return mouse_click(cx, cy, clicks=2, duration=0.0)
        elif action in ("right_click", "rclick"):
            return mouse_click(cx, cy, button="right", duration=0.0)
        else:
            return mouse_click(cx, cy, clicks=clicks, button=button, duration=0.0)

    diff_info = None
    if verify_change and action != "hover":
        # Check visual difference around target or active window
        diff_reg = reg_tuple
        res, diff_info = verify_action_effect(_do_action, region=diff_reg, settle_ms=120.0)
    else:
        res = _do_action()

    return {
        "success": True,
        "action": action,
        "tier_used": tier_used,
        "x": cx,
        "y": cy,
        "visual_changed": diff_info.get("has_changed", False) if diff_info else None,
        "diff": diff_info,
        "result": res,
        "attempts": attempt_logs,
    }
