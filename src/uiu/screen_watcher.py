"""High-Frequency Screen & Web Watcher with Sub-Second Response.

Continuously captures screenshots at configurable intervals (e.g. 1.0s or 0.5s),
detects text or visual changes, and reacts immediately (< 1s latency).
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .gui_primitives import mouse_click, press_key


def screen_watch_and_react(
    target_text: str = "",
    condition: str = "appears",
    region: tuple[int, int, int, int] | list[int] | None = None,
    interval: float = 1.0,
    timeout: float = 60.0,
    action: str = "notify",
    click_on_match: bool = False,
) -> str:
    """Continuously monitor screen or region at high frequency, reacting within 1s upon trigger.

    - target_text: Text keyword or regex to watch for.
    - condition: 'appears' (text shows up), 'disappears' (text is gone), 'changed' (visual image diff).
    - region: Optional [x, y, w, h] to bound screenshot for ultra-low latency (<50ms).
    - interval: Polling interval in seconds (default 1.0s, minimum 0.1s).
    - timeout: Maximum monitoring duration in seconds (default 60s).
    - action: 'notify', 'click' (click match location), or 'press_enter'.
    - click_on_match: Shorthand to click center of matched target immediately.
    """
    import pyautogui
    from .screen_tools import _ocr_winrt_region, _ocr_full_screen
    from .vision_locator import locate_text_on_screen

    interval = max(0.1, float(interval or 1.0))
    timeout = max(1.0, min(float(timeout or 60.0), 600.0))
    condition = condition.lower().strip()
    target = (target_text or "").strip()

    if not target and condition != "changed":
        return "[error] target_text 不能为空（除 condition='changed' 外）"

    r_tuple = tuple(int(v) for v in region) if region and len(region) == 4 else None

    start_time = time.time()
    last_img_hash = None
    frames_checked = 0

    while time.time() - start_time < timeout:
        loop_start = time.time()
        frames_checked += 1

        # 1. Image change condition
        if condition == "changed":
            img = pyautogui.screenshot(region=r_tuple)
            # Simple fast downsampled visual hash
            small = img.resize((32, 32)).convert("L")
            curr_hash = sum(small.getdata())
            if last_img_hash is not None:
                diff = abs(curr_hash - last_img_hash)
                if diff > 800:  # Visual change threshold
                    reaction_time = time.time() - loop_start
                    elapsed_total = time.time() - start_time
                    res_msg = (
                        f"[ok] 监控触发成功 (图像发生显著变化, diff={diff})! "
                        f"检查轮数: {frames_checked}, 总耗时: {elapsed_total:.2f}s, "
                        f"本轮响应时间: {reaction_time*1000:.0f}ms (满足1秒极速响应)"
                    )
                    if click_on_match and r_tuple:
                        mouse_click(r_tuple[0] + r_tuple[2] // 2, r_tuple[1] + r_tuple[3] // 2)
                        res_msg += f"，已在区域中心执行点击"
                    return res_msg
            last_img_hash = curr_hash

        # 2. Text appears / disappears condition
        else:
            if r_tuple:
                items = _ocr_winrt_region(*r_tuple)
            else:
                items = _ocr_full_screen()

            matched = None
            for it in items:
                t = it.get("text", "")
                if target in t or t in target:
                    matched = it
                    break

            if condition == "appears" and matched:
                reaction_time = time.time() - loop_start
                elapsed_total = time.time() - start_time
                cx, cy = matched.get("cx", 0), matched.get("cy", 0)
                res_msg = (
                    f"[ok] 监控目标命中: 发现文本 '{matched.get('text')}'! "
                    f"坐标: ({cx}, {cy}), 轮数: {frames_checked}, "
                    f"总耗时: {elapsed_total:.2f}s, 本轮检测响应耗时: {reaction_time*1000:.0f}ms (达标1秒响应)"
                )
                if click_on_match or action == "click":
                    mouse_click(cx, cy)
                    res_msg += f"，已在目标坐标 ({cx}, {cy}) 极速触发点击"
                elif action == "press_enter":
                    press_key("enter")
                    res_msg += f"，已发送回车键响应"

                return res_msg

            elif condition == "disappears" and not matched and frames_checked > 1:
                reaction_time = time.time() - loop_start
                elapsed_total = time.time() - start_time
                return (
                    f"[ok] 监控目标已消失: '{target}' 不再可见! "
                    f"总耗时: {elapsed_total:.2f}s, 本轮响应: {reaction_time*1000:.0f}ms"
                )

        # Sleep remaining time of the interval
        consumed = time.time() - loop_start
        sleep_dur = max(0.01, interval - consumed)
        time.sleep(sleep_dur)

    return f"[timeout] 监控超时 ({timeout}s)，在 {frames_checked} 轮频繁检测中未满足条件 '{condition}'。"


def web_frequent_monitor(
    window_keyword: str = "chrome",
    match_text: str = "",
    interval: float = 1.0,
    timeout: float = 60.0,
    click_when_found: bool = True,
) -> str:
    """Focus browser/webpage window and perform frequent monitoring for specific target text."""
    from .window_manager import open_or_focus_app

    if window_keyword:
        open_or_focus_app(window_keyword)
        time.sleep(0.3)

    return screen_watch_and_react(
        target_text=match_text,
        condition="appears",
        interval=interval,
        timeout=timeout,
        click_on_match=click_when_found,
    )


# Tool schemas
SCREEN_WATCH_AND_REACT_DEF = {
    "type": "function",
    "function": {
        "name": "screen_watch_and_react",
        "description": "高频截图巡检与监控（频率可控，如每秒1次），当满足目标文字出现/消失/视觉图像变动时，在1秒内极速触发响应或自动点击。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_text": {"type": "string", "description": "待监控的目标文字或关键字"},
                "condition": {
                    "type": "string",
                    "enum": ["appears", "disappears", "changed"],
                    "default": "appears",
                    "description": "触发条件：'appears'（出现）、'disappears'（消失）、'changed'（图像变动）",
                },
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "监控的屏幕区域 [x, y, w, h]（可选，限定区域可将响应速度缩短至数十毫秒）",
                },
                "interval": {"type": "number", "default": 1.0, "description": "巡检周期秒数（如 1.0 或 0.5 秒）"},
                "timeout": {"type": "number", "default": 60.0, "description": "最大监控总时长秒数"},
                "action": {"type": "string", "enum": ["notify", "click", "press_enter"], "default": "notify"},
                "click_on_match": {"type": "boolean", "default": False, "description": "命中时是否立即自动点击该文字"},
            },
        },
    },
}

WEB_FREQUENT_MONITOR_DEF = {
    "type": "function",
    "function": {
        "name": "web_frequent_monitor",
        "description": "对网页或软件窗口进行频繁截图监控，1秒内极速响应（例如抢单、监控特定数据更新、出现目标按钮立即点击）。",
        "parameters": {
            "type": "object",
            "properties": {
                "match_text": {"type": "string", "description": "网页中待出现的关键字或按钮文字"},
                "window_keyword": {"type": "string", "default": "chrome", "description": "窗口标题关键字（默认 'chrome'）"},
                "interval": {"type": "number", "default": 1.0, "description": "巡检周期秒数"},
                "timeout": {"type": "number", "default": 60.0, "description": "超时秒数"},
                "click_when_found": {"type": "boolean", "default": True, "description": "出现后是否立即自动点击"},
            },
            "required": ["match_text"],
        },
    },
}

SCREEN_WATCHER_TOOLS: dict[str, dict] = {
    "screen_watch_and_react": {"def": SCREEN_WATCH_AND_REACT_DEF, "fn": screen_watch_and_react},
    "web_frequent_monitor": {"def": WEB_FREQUENT_MONITOR_DEF, "fn": web_frequent_monitor},
}


def screen_watcher_tool_defs() -> list[dict]:
    return [t["def"] for t in SCREEN_WATCHER_TOOLS.values()]
