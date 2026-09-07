"""Virtual Scrolling Probe & Boundary Diffing Engine.

Enables agents to explore content outside the visible viewport:
1. Long WeChat conversation histories
2. Long tables and web pages
3. Scroll-until-found pattern with visual boundary stop detection (avoids infinite scrolling loops)
"""

from __future__ import annotations

import time
from typing import Any


def scroll_and_find(
    target: str,
    anchor: str | None = None,
    max_scrolls: int = 6,
    scroll_clicks: int = -4,  # Negative = scroll down, Positive = scroll up
    region: tuple[int, int, int, int] | None = None,
    window_title: str | None = None,
    settle_ms: float = 200.0,
) -> dict[str, Any]:
    """Scroll container until target element becomes visible, stopping if container boundary is reached."""
    from .gui_primitives import mouse_scroll
    from .screen_diff import compute_screen_diff
    from .screen_tools import safe_screenshot
    from .spatial_locator import find_element_by_relation
    from .vision_locator import find_text_element, get_screen_elements
    from .window_manager import focus_window, open_or_focus_app

    if window_title:
        open_or_focus_app(window_title)
        time.sleep(0.15)

    r_tuple = tuple(region) if region and len(region) == 4 else None

    # Determine scroll anchor point (center of region or center of screen)
    if r_tuple:
        scroll_x = r_tuple[0] + r_tuple[2] // 2
        scroll_y = r_tuple[1] + r_tuple[3] // 2
    else:
        scroll_x, scroll_y = 960, 540

    total_scrolls = 0
    hit_boundary = False

    for scroll_idx in range(max_scrolls + 1):
        # 1. Search in current viewport
        if anchor:
            elem = find_element_by_relation(
                target=target,
                anchor=anchor,
                region=r_tuple,
                window_title=window_title,
            )
        else:
            elem = find_text_element(target, region=r_tuple)

        if elem:
            return {
                "found": True,
                "target": target,
                "element": elem,
                "total_scrolls": total_scrolls,
                "hit_boundary": False,
            }

        # If we have reached max scrolls, exit
        if scroll_idx >= max_scrolls:
            break

        # 2. Take pre-scroll snapshot to detect if scrolling actually moved content
        before_shot = safe_screenshot(region=r_tuple)

        # 3. Perform scroll
        mouse_scroll(scroll_clicks, x=scroll_x, y=scroll_y)
        total_scrolls += 1

        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)

        # 4. Take post-scroll snapshot and compute visual diff
        after_shot = safe_screenshot(region=r_tuple)
        diff = compute_screen_diff(before_shot, after_shot)

        # If screen changed less than 0.5%, we hit the bottom/top boundary!
        if diff["change_ratio"] < 0.005:
            hit_boundary = True
            break

    return {
        "found": False,
        "target": target,
        "element": None,
        "total_scrolls": total_scrolls,
        "hit_boundary": hit_boundary,
        "message": "已触达滚动边界" if hit_boundary else f"已达最大滚动次数 ({max_scrolls}) 仍未找到目标",
    }
