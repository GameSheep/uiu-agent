"""Universal Vision & Element Locator."""

from __future__ import annotations

import time
from typing import Any


def capture_screen(region: tuple[int, int, int, int] | None = None):
    import pyautogui
    return pyautogui.screenshot(region=region)


def get_screen_elements(region: tuple[int, int, int, int] | None = None) -> list[dict[str, Any]]:
    from .screen_tools import _ocr_full_screen

    all_items = _ocr_full_screen()
    if not region:
        return all_items

    r_left, r_top, r_w, r_h = region
    r_right, r_bottom = r_left + r_w, r_top + r_h

    filtered = []
    for it in all_items:
        cx, cy = it.get("cx", -1), it.get("cy", -1)
        if r_left <= cx <= r_right and r_top <= cy <= r_bottom:
            filtered.append(it)
    return filtered


def locate_text_on_screen(
    target_text: str,
    region: tuple[int, int, int, int] | None = None,
    exact: bool = False
) -> dict | None:
    target = target_text.strip()
    if not target:
        return None

    items = get_screen_elements(region)
    exact_matches = []
    fuzzy_matches = []

    for it in items:
        t = it.get("text", "").strip()
        if not t:
            continue
        if t == target:
            exact_matches.append(it)
        elif not exact and (target in t or t in target):
            fuzzy_matches.append(it)

    if exact_matches:
        return exact_matches[0]
    if fuzzy_matches:
        return min(fuzzy_matches, key=lambda i: abs(len(i.get("text", "")) - len(target)))
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
        elem = locate_text_on_screen(target_text, region=scroll_zone, exact=False)
        if elem:
            return elem
        if i < max_scrolls:
            pyautogui.scroll(scroll_amount)
            time.sleep(0.4)

    return None