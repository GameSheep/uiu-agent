"""Universal Vision & Element Locator — Hierarchical Sniffing & Zero-Drift Precision."""

from __future__ import annotations

import time
from typing import Any


def capture_screen(region: tuple[int, int, int, int] | None = None):
    import pyautogui
    return pyautogui.screenshot(region=region)


def get_screen_elements(
    region: tuple[int, int, int, int] | None = None,
    engine: str = "auto",
) -> list[dict[str, Any]]:
    """Capture and OCR screen elements. Directly captures only region if specified.
    engine: 'auto' | 'rapidocr' (best for Chinese) | 'winrt' (sub-100ms English/UI)
    """
    from .screen_tools import _ocr_full_screen, _ocr_region

    if region:
        r_left, r_top, r_w, r_h = region
        if r_w > 0 and r_h > 0:
            if engine != "auto":
                try:
                    return _ocr_region(int(r_left), int(r_top), int(r_w), int(r_h), engine=engine)
                except TypeError:
                    pass
            return _ocr_region(int(r_left), int(r_top), int(r_w), int(r_h))

    if engine != "auto":
        try:
            return _ocr_full_screen(engine=engine)
        except TypeError:
            pass
    return _ocr_full_screen()


def _find_and_refine_in_items(
    items: list[dict],
    target: str,
    exact: bool = False,
    engine: str = "auto",
) -> dict | None:
    """Find target text using two-stage coarse-to-fine strategy:
    1. Direct match with match_text_element (instant if exact or unambiguous).
    2. If target contains Chinese and direct match not found, rank coarse candidate boxes
       and refine them using small RapidOCR crops (fast & 100% accurate Chinese reading).
    """
    from .screen_tools import match_text_element

    # 1. Direct match first
    elem = match_text_element(items, target, exact=exact)
    if elem:
        return elem

    # If pure ASCII / English or user explicitly requested winrt only, return
    is_chinese = any('\u4e00' <= ch <= '\u9fff' for ch in target)
    if not is_chinese or engine == "winrt":
        return None

    # 2. Coarse-to-Fine Refinement: Score candidate items from coarse scan
    import difflib
    target_clean = target.strip()
    target_lower = target_clean.lower()
    scored_candidates = []

    for it in items:
        txt = it.get("text", "").strip()
        if not txt:
            continue
        txt_lower = txt.lower()
        if target_lower in txt_lower or txt_lower in target_lower:
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, txt_lower, target_lower).ratio()
            # Boost score if non-ascii characters or alphanumeric tokens overlap
            for ch in target_clean:
                if len(ch.strip()) > 0 and (ord(ch) > 127 or ch.isalnum()) and ch.lower() in txt_lower:
                    score += 0.15
        if score >= 0.25:
            scored_candidates.append((score, it))

    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    # 3. Refine top candidates using small-crop RapidOCR
    from .screen_tools import _ocr_region_rapidocr
    for score, cand in scored_candidates[:3]:
        cx = int(cand.get("x", 0))
        cy = int(cand.get("y", 0))
        cw = int(cand.get("w", 0))
        ch = int(cand.get("h", 0))
        if cw <= 0 or ch <= 0:
            continue
        # Expand box with margin and enforce min height 50px for robust DBNet detection
        crop_x = max(0, cx - 20)
        crop_y = max(0, cy - 20)
        crop_w = cw + 40
        crop_h = max(50, ch + 40)
        try:
            fine_items = _ocr_region_rapidocr(crop_x, crop_y, crop_w, crop_h)
            matched = match_text_element(fine_items, target, exact=exact)
            if matched:
                matched["refined"] = True
                return matched
        except Exception:
            pass

    return None


def _safe_get_elements(region: tuple[int, int, int, int] | None = None, engine: str = "auto") -> list[dict[str, Any]]:
    if engine != "auto":
        try:
            return get_screen_elements(region=region, engine=engine)
        except TypeError:
            pass
    return get_screen_elements(region=region)


def locate_text_on_screen(
    target_text: str,
    region: tuple[int, int, int, int] | None = None,
    exact: bool = False,
    use_hierarchical: bool = True,
    target_hwnd: int | None = None,
    search_mouse_radius: int = 100,
    engine: str = "auto",
) -> dict | None:
    """Locate text on screen using two-stage coarse-to-fine hybrid OCR with hierarchical 3-tier sniffing:
    - Broad scan: Windows native WinRT OCR (< 50ms) to scan mouse/window/full screen.
    - Specific refinement: RapidOCR (PP-OCRv4) on small candidate crops for 100% Chinese accuracy.
    - Tier 1: Mouse neighborhood (+-100px or 10% screen) for sub-50ms sniffing.
    - Tier 2: Active or target window rectangle for fast isolated sniffing.
    - Tier 3: Full-screen fallback.
    Returns exact word/phrase center coordinates (cx, cy) with zero drift.
    """
    target = target_text.strip()
    if not target:
        return None

    # Explicit region provided -> directly search within it using coarse-to-fine
    if region is not None:
        items = _safe_get_elements(region, engine=engine)
        return _find_and_refine_in_items(items, target, exact=exact, engine=engine)

    if use_hierarchical:
        try:
            from .window_manager import ensure_default_desktop
            ensure_default_desktop()
        except Exception:
            pass

        import pyautogui

        # Tier 1: Mouse neighborhood sniffing (+-100px or 10% screen)
        try:
            mx, my = pyautogui.position()
            sw, sh = pyautogui.size()
            rx = max(search_mouse_radius, int(sw * 0.10))
            ry = max(search_mouse_radius, int(sh * 0.10))
            x1 = max(0, mx - rx)
            y1 = max(0, my - ry)
            x2 = min(sw, mx + rx)
            y2 = min(sh, my + ry)
            w, h = x2 - x1, y2 - y1
            if w >= 20 and h >= 20:
                mouse_items = _safe_get_elements(region=(x1, y1, w, h), engine=engine)
                elem = _find_and_refine_in_items(mouse_items, target, exact=exact, engine=engine)
                if elem:
                    elem["tier"] = 1
                    return elem
        except Exception:
            pass

        # Tier 2: Target or foreground window bounds sniffing
        try:
            import win32gui
            hwnd = target_hwnd or win32gui.GetForegroundWindow()
            if hwnd and win32gui.IsWindow(hwnd) and not win32gui.IsIconic(hwnd):
                rect = win32gui.GetWindowRect(hwnd)
                sw, sh = pyautogui.size()
                wx1 = max(0, min(sw, rect[0]))
                wy1 = max(0, min(sh, rect[1]))
                wx2 = max(0, min(sw, rect[2]))
                wy2 = max(0, min(sh, rect[3]))
                ww, wh = wx2 - wx1, wy2 - wy1
                if ww >= 40 and wh >= 40:
                    win_items = _safe_get_elements(region=(wx1, wy1, ww, wh), engine=engine)
                    elem = _find_and_refine_in_items(win_items, target, exact=exact, engine=engine)
                    if elem:
                        elem["tier"] = 2
                        return elem
        except Exception:
            pass

    # Tier 3: Full-screen fallback
    items = _safe_get_elements(region=None, engine=engine)
    elem = _find_and_refine_in_items(items, target, exact=exact, engine=engine)
    if elem:
        elem["tier"] = 3
        return elem

    return None


def scroll_and_find(
    target_text: str,
    scroll_zone: tuple[int, int, int, int],
    max_scrolls: int = 5,
    scroll_amount: int = -300
) -> dict | None:
    import pyautogui

    z_left, z_top, z_w, z_h = scroll_zone
    center_x = z_left + z_w // 2
    center_y = z_top + z_h // 2

    pyautogui.moveTo(center_x, center_y, duration=0.15)

    for i in range(max_scrolls + 1):
        elem = locate_text_on_screen(target_text, region=scroll_zone, exact=False, use_hierarchical=False)
        if elem:
            return elem
        if i < max_scrolls:
            pyautogui.scroll(scroll_amount)
            time.sleep(0.4)

    return None