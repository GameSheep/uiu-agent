"""Autonomous UI Recovery & Interruption Handler — State-of-the-Art Agent Resilience Pattern.

Solves the primary failure modes in real-world desktop automation:
1. wait_screen_stable: Waits until UI rendering / animations / spinners settle before interacting.
2. detect_modal_dialog: Scans for unexpected blocking popups (updates, confirm prompts, warnings).
3. dismiss_blocking_dialog: Automatically disarms non-critical blocking modals (Esc, '稍后', '取消', '关闭').
4. resilient_click: Self-healing interaction that handles animation lag and popup interruptions automatically.
"""

from __future__ import annotations

import time
from typing import Any
import cv2
import numpy as np


def wait_screen_stable(
    region: tuple[int, int, int, int] | list[int] | None = None,
    max_wait_ms: float = 2500.0,
    check_interval_ms: float = 80.0,
    stability_threshold: float = 0.0005,
) -> bool:
    """Wait until screen/region stops changing (animation, transition, or loading spinner finished).

    Returns True if screen stabilized within max_wait_ms, False if still continuously animating.
    """
    import pyautogui
    from .screen_diff import compute_screen_diff

    r_tuple = tuple(region) if region and len(region) == 4 else None
    t0 = time.perf_counter()
    timeout_s = max_wait_ms / 1000.0
    interval_s = check_interval_ms / 1000.0

    from .screen_tools import safe_screenshot

    last_shot = safe_screenshot(region=r_tuple)
    stable_hits = 0
    required_stable_hits = 2  # 2 consecutive stable frames

    while (time.perf_counter() - t0) < timeout_s:
        time.sleep(interval_s)
        cur_shot = safe_screenshot(region=r_tuple)

        diff = compute_screen_diff(last_shot, cur_shot)
        last_shot = cur_shot

        if diff["change_ratio"] <= stability_threshold:
            stable_hits += 1
            if stable_hits >= required_stable_hits:
                return True
        else:
            stable_hits = 0

    return False


def detect_modal_dialog(
    target_hwnd: int | None = None,
    region: tuple[int, int, int, int] | list[int] | None = None,
) -> dict[str, Any] | None:
    """Detect if an unexpected blocking modal dialog or alert box is currently active."""
    # 1. Try Windows UIA for Dialog / Alert window controls
    try:
        import uiautomation as auto
        from .window_manager import ensure_default_desktop
        ensure_default_desktop()
        root = auto.GetRootControl()
        for win in root.GetChildren():
            ctype = win.ControlTypeName
            name = (win.Name or "").strip()
            # Modal dialog hints
            if ctype in ("WindowControl", "PaneControl") and any(k in name for k in ("提示", "更新", "警告", "确认", "Notice", "Alert", "Confirm", "Update")):
                rect = win.BoundingRectangle
                if (rect.right - rect.left) > 100 and (rect.bottom - rect.top) > 60:
                    return {
                        "detected": True,
                        "type": "uia_dialog",
                        "title": name,
                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                        "cx": (rect.left + rect.right) // 2,
                        "cy": (rect.top + rect.bottom) // 2,
                    }
    except Exception:
        pass

    # 2. Vision fallback: detect high-contrast central floating boxes
    from .icon_locator import detect_icon_regions
    from .vision_locator import locate_text_on_screen

    dialog_keywords = ["取消", "稍后", "关闭", "我知道了", "Dismiss", "Cancel", "Close", "OK"]
    for kw in dialog_keywords:
        elem = locate_text_on_screen(kw, region=tuple(region) if region else None)
        if elem:
            return {
                "detected": True,
                "type": "vision_button",
                "title": f"发现含 '{kw}' 的可能弹窗按钮",
                "dismiss_btn": kw,
                "cx": int(round(elem["cx"])),
                "cy": int(round(elem["cy"])),
            }

    return None


def dismiss_blocking_dialog() -> bool:
    """Safely disarm and dismiss an active blocking popup (Esc, '取消', '稍后')."""
    from .gui_primitives import press_key, mouse_click

    # Method 1: Check for explicit dismiss buttons
    dlg = detect_modal_dialog()
    if dlg and dlg.get("cx") and dlg.get("cy"):
        mouse_click(dlg["cx"], dlg["cy"], duration=0.0)
        time.sleep(0.15)
        return True

    # Method 2: Universal Esc dismiss
    press_key("esc")
    time.sleep(0.1)
    return True


def resilient_click(
    target: str | dict[str, Any],
    region: tuple[int, int, int, int] | list[int] | None = None,
    wait_stable: bool = True,
    auto_dismiss_popups: bool = True,
) -> dict[str, Any]:
    """Execute high-reliability self-healing click with stability wait and popup disarming."""
    from .smart_interact import smart_interact

    t0 = time.perf_counter()
    logs = []

    # Step 1: Wait for screen to settle
    if wait_stable:
        is_stable = wait_screen_stable(region=region, max_wait_ms=1200.0)
        logs.append(f"画面沉降核验: {'已静止' if is_stable else '达到上限，继续执行'}")

    # Step 2: Detect & dismiss unexpected popups if any
    if auto_dismiss_popups:
        dlg = detect_modal_dialog(region=region)
        if dlg:
            logs.append(f"检测到阻塞弹窗: {dlg.get('title', '未知')}，自动尝试消解")
            dismiss_blocking_dialog()
            time.sleep(0.15)

    # Step 3: Execute smart interact
    res = smart_interact(target, action="click", region=region, verify_change=True)
    logs.extend(res.get("attempts", []))

    # Step 4: Self-healing retry if initial interaction showed no visual response
    if not res.get("success") or res.get("visual_changed") is False:
        logs.append("初次点击未产生视觉变化，触发自愈容错：检查阻断弹窗并微调重试")
        dismiss_blocking_dialog()
        time.sleep(0.1)
        retry_res = smart_interact(target, action="click", region=region, verify_change=True)
        if retry_res.get("success"):
            res = retry_res
            logs.append(f"自愈重试成功 (命中: {retry_res.get('tier_used')})")

    res["total_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    res["recovery_logs"] = logs
    return res
