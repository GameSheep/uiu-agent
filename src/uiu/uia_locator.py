"""Universal UI Automation (UIA) Locator — Sub-millisecond Accessibility Control Sniffing.

Directly reads Windows UI Automation tree (aria-label, Name, AutomationId, ControlType)
without vision or OCR, bypassing screen capture entirely.
"""

from __future__ import annotations

import time
from typing import Any


def _normalize_type(type_name: str | None) -> str:
    if not type_name:
        return ""
    t = type_name.strip()
    if not t.endswith("Control"):
        t += "Control"
    return t


def find_uia_control(
    name: str | None = None,
    control_type: str | None = "Button",
    window_title: str | None = None,
    automation_id: str | None = None,
    search_depth: int = 8,
) -> dict[str, Any] | None:
    """Locate a UI control by its accessibility properties (Name, aria-label, AutomationId, ControlType).

    Returns:
        {'found': True, 'name': '...', 'type': 'ButtonControl', 'rect': [l, t, r, b], 'cx': cx, 'cy': cy}
        or None if not found.
    """
    try:
        import uiautomation as auto
    except ImportError:
        return None

    from .window_manager import ensure_default_desktop, find_window
    ensure_default_desktop()

    target_root = None
    if window_title:
        win_info = find_window(window_title)
        if win_info and win_info.get("hwnd"):
            try:
                target_root = auto.ControlFromHandle(win_info["hwnd"])
            except Exception:
                pass
        if not target_root:
            try:
                target_root = auto.WindowControl(searchDepth=2, SubName=window_title)
                if not target_root.Exists(0):
                    target_root = None
            except Exception:
                pass

    if target_root is None:
        target_root = auto.GetRootControl()

    norm_type = _normalize_type(control_type) if control_type else None
    name_clean = name.strip().lower() if name else None
    auto_id_clean = automation_id.strip() if automation_id else None

    matched_control = None

    def _match(ctrl: auto.Control) -> bool:
        if norm_type and ctrl.ControlTypeName != norm_type:
            return False
        if auto_id_clean:
            try:
                if ctrl.AutomationId != auto_id_clean:
                    return False
            except Exception:
                return False
        if name_clean:
            try:
                c_name = (ctrl.Name or "").strip().lower()
                if name_clean not in c_name:
                    return False
            except Exception:
                return False
        return True

    # Search with controlled depth
    queue = [(target_root, 1)]
    visited_count = 0
    max_nodes = 300

    while queue and visited_count < max_nodes:
        cur, depth = queue.pop(0)
        visited_count += 1

        if depth > 1 and _match(cur):
            matched_control = cur
            break

        if depth < search_depth:
            try:
                children = cur.GetChildren()
                for ch in children:
                    queue.append((ch, depth + 1))
            except Exception:
                pass

    if matched_control:
        try:
            rect = matched_control.BoundingRectangle
            l, t, r, b = rect.left, rect.top, rect.right, rect.bottom
            w, h = r - l, b - t
            if w > 0 and h > 0:
                return {
                    "found": True,
                    "name": matched_control.Name,
                    "control_type": matched_control.ControlTypeName,
                    "automation_id": getattr(matched_control, "AutomationId", ""),
                    "rect": [l, t, r, b],
                    "w": w,
                    "h": h,
                    "cx": l + w // 2,
                    "cy": t + h // 2,
                }
        except Exception:
            pass

    return None


def list_uia_controls(
    window_title: str | None = None,
    control_types: list[str] | None = None,
    max_count: int = 30,
) -> list[dict[str, Any]]:
    """List interactive controls in a window with their labels and coordinates."""
    try:
        import uiautomation as auto
    except ImportError:
        return []

    from .window_manager import ensure_default_desktop, find_window
    ensure_default_desktop()

    root = None
    if window_title:
        win_info = find_window(window_title)
        if win_info and win_info.get("hwnd"):
            try:
                root = auto.ControlFromHandle(win_info["hwnd"])
            except Exception:
                pass

    if not root:
        root = auto.GetRootControl()

    filter_types = {_normalize_type(t) for t in control_types} if control_types else None
    results = []

    def _walk(ctrl, depth):
        if len(results) >= max_count or depth > 5:
            return
        try:
            name = (ctrl.Name or "").strip()
            ctype = ctrl.ControlTypeName
            rect = ctrl.BoundingRectangle
            w, h = rect.right - rect.left, rect.bottom - rect.top

            is_interactive = ctype in (
                "ButtonControl", "EditControl", "HyperlinkControl", "MenuItemControl",
                "TabItemControl", "ListItemControl", "CheckBoxControl"
            )

            if (filter_types is None and is_interactive) or (filter_types and ctype in filter_types):
                if w > 4 and h > 4:
                    results.append({
                        "name": name,
                        "type": ctype,
                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                        "cx": (rect.left + rect.right) // 2,
                        "cy": (rect.top + rect.bottom) // 2,
                    })

            for ch in ctrl.GetChildren():
                _walk(ch, depth + 1)
        except Exception:
            pass

    _walk(root, 1)
    return results
