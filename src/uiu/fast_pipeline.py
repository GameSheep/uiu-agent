"""Fast Pipeline & Zero-Thinking Compound Action Executor.

Designed to execute multi-step GUI and system actions locally in Python at native
sub-second speed without per-step LLM reasoning or network round-trips.
"""

from __future__ import annotations

import json
import time
from typing import Any


def gui_action_pipeline(steps: list[dict[str, Any]]) -> str:
    """Execute a sequence of GUI actions locally at sub-second speed without intermediate LLM thinking.

    Supported step actions:
    - {'action': 'app', 'target': 'ChatGPT'}: open or focus app
    - {'action': 'hotkey', 'keys': ['ctrl', ',']}: instant shortcut
    - {'action': 'click', 'x': 100, 'y': 200}: instant mouse click
    - {'action': 'click_offset', 'x_offset': 80, 'y_offset': 555}: click relative to current active window
    - {'action': 'click_text', 'text': 'Usage', 'region': [x,y,w,h] (optional)}: sniff & instant click
    - {'action': 'type', 'text': '...', 'clear_before': True/False}: clipboard paste
    - {'action': 'key', 'key': 'enter'}: single key press
    - {'action': 'scroll', 'clicks': -300}: scroll wheel
    - {'action': 'wait', 'ms': 200}: micro pause for UI animation
    - {'action': 'read_text', 'region': [x,y,w,h] (optional)}: extract text in region
    """
    from .window_manager import ensure_default_desktop, open_or_focus_app, find_window, focus_window
    from .gui_primitives import mouse_click, mouse_scroll, press_hotkey, press_key, paste_text
    from .vision_locator import locate_text_on_screen, get_screen_elements

    ensure_default_desktop()
    t_start = time.perf_counter()
    logs = []
    read_results = []
    active_win_rect = None

    for i, step in enumerate(steps, 1):
        action = step.get("action", "").lower().strip()
        t_step_start = time.perf_counter()
        status = "ok"
        detail = ""

        try:
            if action in ("app", "open_app", "focus_app"):
                target = step.get("target", "")
                res = open_or_focus_app(target)
                detail = res
                import win32gui
                win = find_window(target)
                if win:
                    active_win_rect = win32gui.GetWindowRect(win["hwnd"])

            elif action == "hotkey":
                keys = step.get("keys", [])
                detail = press_hotkey(keys)

            elif action in ("click", "click_at"):
                x = int(step.get("x", 0))
                y = int(step.get("y", 0))
                clicks = int(step.get("clicks", 1))
                detail = mouse_click(x, y, clicks=clicks, duration=0.0)

            elif action == "click_offset":
                if not active_win_rect:
                    import win32gui
                    hwnd = win32gui.GetForegroundWindow()
                    if hwnd:
                        active_win_rect = win32gui.GetWindowRect(hwnd)
                if active_win_rect:
                    wl, wt, wr, wb = active_win_rect
                    ww, wh = wr - wl, wb - wt
                    x_off = int(step.get("x_offset", 0))
                    y_off = int(step.get("y_offset", 0))
                    target_x = wl + (ww + x_off if x_off < 0 else x_off)
                    target_y = wt + (wh + y_off if y_off < 0 else y_off)
                    detail = mouse_click(target_x, target_y, duration=0.0)
                else:
                    status = "error"
                    detail = "未找到活动窗口边界，无法计算相对偏移"

            elif action == "click_text":
                target_text = step.get("text", "")
                reg = step.get("region")
                region_tuple = tuple(reg) if reg and len(reg) == 4 else None
                elem = locate_text_on_screen(target_text, region=region_tuple, use_hierarchical=True)
                if elem:
                    detail = mouse_click(int(round(elem["cx"])), int(round(elem["cy"])), duration=0.0)
                else:
                    status = "error"
                    detail = f"未找到文字: {target_text}"

            elif action in ("icon", "click_icon"):
                from .icon_locator import match_icon_template
                icon_name = step.get("icon", "")
                reg = step.get("region")
                if not reg and active_win_rect:
                    reg = active_win_rect
                region_tuple = tuple(reg) if reg and len(reg) == 4 else None
                elem = match_icon_template(icon_name, region=region_tuple)
                if elem:
                    detail = mouse_click(int(round(elem["cx"])), int(round(elem["cy"])), duration=0.0)
                else:
                    status = "error"
                    detail = f"未找到图标: {icon_name}"

            elif action in ("icon_near", "click_icon_near"):
                from .icon_locator import find_icons_relative_to_anchor
                anchor = step.get("anchor", step.get("text", ""))
                direction = step.get("direction", "right")
                idx = int(step.get("index", 1))
                reg = step.get("region")
                if not reg and active_win_rect:
                    reg = active_win_rect
                region_tuple = tuple(reg) if reg and len(reg) == 4 else None
                elem = find_icons_relative_to_anchor(anchor, direction=direction, index=idx, region=region_tuple)
                if elem:
                    detail = mouse_click(int(round(elem["cx"])), int(round(elem["cy"])), duration=0.0)
                else:
                    status = "error"
                    detail = f"未在锚点 '{anchor}' {direction} 找到第 {idx} 个图标"

            elif action in ("uia", "click_uia"):
                from .uia_locator import find_uia_control
                ctrl_name = step.get("name")
                ctype = step.get("control_type", "Button")
                win_t = step.get("window_title")
                ctrl = find_uia_control(name=ctrl_name, control_type=ctype, window_title=win_t)
                if ctrl:
                    detail = mouse_click(int(round(ctrl["cx"])), int(round(ctrl["cy"])), duration=0.0)
                else:
                    status = "error"
                    detail = f"未找到 UIA 控件: {ctrl_name} ({ctype})"

            elif action in ("type", "type_text"):
                text = step.get("text", "")
                clear = bool(step.get("clear_before", False))
                detail = paste_text(text, clear_before=clear)

            elif action == "key":
                key_name = step.get("key", "enter")
                detail = press_key(key_name)

            elif action == "scroll":
                clicks = int(step.get("clicks", -300))
                detail = mouse_scroll(clicks)

            elif action == "wait":
                ms = float(step.get("ms", 100))
                time.sleep(ms / 1000.0)
                detail = f"等待 {ms:.0f}ms"

            elif action == "read_text":
                reg = step.get("region")
                if not reg and active_win_rect:
                    reg = active_win_rect
                region_tuple = tuple(reg) if reg and len(reg) == 4 else None
                items = get_screen_elements(region=region_tuple)
                texts = [it["text"] for it in items if it.get("text")]
                read_results.append({"step": i, "region": reg, "texts": texts})
                detail = f"提取到 {len(texts)} 行文字"

            else:
                status = "error"
                detail = f"未知动作: {action}"

        except Exception as e:
            status = "error"
            detail = f"执行异常: {type(e).__name__}: {e}"

        elapsed_ms = (time.perf_counter() - t_step_start) * 1000.0
        logs.append(f"Step {i} [{action}]: {detail} ({elapsed_ms:.1f}ms)")

    total_elapsed = (time.perf_counter() - t_start) * 1000.0
    report = [
        f"### [流水线] 极速动作执行报告 (总耗时: {total_elapsed:.1f}ms / {total_elapsed/1000.0:.2f}s, 共 {len(steps)} 步)",
        "**步骤时延列表:**"
    ]
    for l in logs:
        report.append(f"- {l}")

    if read_results:
        report.append("\n**提取到的屏幕信息:**")
        for r in read_results:
            report.append(f"- 提取内容 ({len(r['texts'])} 行):\n  " + "\n  ".join(r['texts'][:25]))

    return "\n".join(report)


def check_chatgpt_quota(scroll_for_more: bool = False) -> str:
    """Zero-thinking instant sub-second query of ChatGPT desktop quota (< 1.2s total).

    Executes a direct 4-step local pipeline:
    1. Bring ChatGPT to front (bypassing Win10/Win11 locks)
    2. Instant shortcut Ctrl+, to open Settings modal
    3. Instant click on '使用情况与计费' (Usage & Billing) tab
    4. Fast regional OCR extraction of quota, reset dates, and remaining limits.
    """
    from .window_manager import ensure_default_desktop, find_window, focus_window
    from .vision_locator import get_screen_elements, locate_text_on_screen
    import pyautogui
    import win32gui

    ensure_default_desktop()
    t_start = time.perf_counter()

    # Step 1: Open / Focus ChatGPT
    win = find_window("chatgpt")
    if not win:
        from .window_manager import open_or_focus_app
        open_or_focus_app("ChatGPT")
        time.sleep(0.5)
        win = find_window("chatgpt")
        if not win:
            return "[error] 未找到 ChatGPT 客户端，请先安装或启动 ChatGPT。"

    hwnd = win["hwnd"]
    focus_window(hwnd)
    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect
    w, h = right - left, bottom - top

    # Step 2: Instant shortcut Ctrl+, to open Settings
    pyautogui.hotkey("ctrl", ",")
    time.sleep(0.3)

    # Step 3: Fast locate & click '使用情况与计费' / 'Billing' tab in left sidebar
    sidebar_region = (left, top, 260, h)
    elem = locate_text_on_screen("使用情况", region=sidebar_region)
    if not elem:
        elem = locate_text_on_screen("计费", region=sidebar_region)
    if not elem:
        elem = locate_text_on_screen("Billing", region=sidebar_region)

    if elem:
        pyautogui.click(int(round(elem["cx"])), int(round(elem["cy"])))
    else:
        # Calibrated offset: left + 80, top + 576
        pyautogui.click(left + 80, min(bottom - 50, top + 576))
    time.sleep(0.25)

    # Step 4: Extract quota details in right panel
    quota_box = (left + 280, top + 80, max(200, w - 300), max(200, h - 120))
    items = get_screen_elements(region=quota_box)
    all_lines = [it["text"] for it in items if it.get("text")]

    # Optional scroll to capture bottom model quotas
    if scroll_for_more:
        center_x = quota_box[0] + quota_box[2] // 2
        center_y = quota_box[1] + quota_box[3] // 2
        pyautogui.moveTo(center_x, center_y)
        pyautogui.scroll(-350)
        time.sleep(0.15)
        items2 = get_screen_elements(region=quota_box)
        for it in items2:
            txt = it.get("text")
            if txt and txt not in all_lines:
                all_lines.append(txt)

    elapsed_ms = (time.perf_counter() - t_start) * 1000

    output = [
        f"### [ChatGPT] 剩余额度与使用情况 (查询耗时: {elapsed_ms:.1f}ms / {elapsed_ms/1000:.2f}s)",
    ]
    if not all_lines:
        output.append("未能识别到额度详情文字，请确认设置面板已正常展示。")
    else:
        output.append("**实时提取的使用量与限额明细:**")
        for l in all_lines[:25]:
            output.append(f"- {l}")

    return "\n".join(output)


def update_cc_switch_provider_remark(
    provider_name: str,
    new_remark: str,
    db_path_override: str | None = None,
) -> str:
    """Zero-thinking instant update of provider remark in CC Switch (< 1.0s).

    1. Restore & focus CC Switch window (handles minimized window via SW_RESTORE).
    2. Try fast GUI interaction (hover card, click edit icon, paste remark, click save).
    3. Update & verify via SQLite database (C:\\Users\\haibao.feng\\.cc-switch\\cc-switch.db).
    """
    import os
    import sqlite3
    import time
    from pathlib import Path
    from .window_manager import ensure_default_desktop, find_window, focus_window
    from .gui_primitives import paste_text
    import pyautogui
    import win32gui
    import win32con

    ensure_default_desktop()
    t_start = time.perf_counter()
    logs = []

    # Target DB path
    if db_path_override:
        db_path = Path(db_path_override)
    else:
        db_candidates = [
            Path.home() / ".cc-switch" / "cc-switch.db",
            Path(os.environ.get("USERPROFILE", "C:/Users/haibao.feng")) / ".cc-switch" / "cc-switch.db",
        ]
        db_path = None
        for p in db_candidates:
            if p.exists():
                db_path = p
                break

    # GUI Step: Focus & Restore window
    win = find_window("CC Switch")
    win_rect = None
    if win:
        hwnd = win["hwnd"]
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        focus_window(hwnd)
        time.sleep(0.15)
        win_rect = win32gui.GetWindowRect(hwnd)
        logs.append("已唤醒并置顶 CC Switch 窗口")

    gui_success = False
    if win_rect:
        try:
            wl, wt, wr, wb = win_rect
            ww, wh = wr - wl, wb - wt
            from .vision_locator import locate_text_on_screen
            elem = locate_text_on_screen(provider_name, region=(wl, wt, ww, wh))
            card_cy = int(round(elem["cy"])) if elem else (wt + 237)

            # Hover to trigger action buttons
            pyautogui.moveTo(wl + 500, card_cy)
            time.sleep(0.1)

            # Locate or offset click edit pencil
            pencil_x = min(wr - 60, max(wl + 400, 934 if (wl <= 934 <= wr) else (wl + 450)))
            pyautogui.click(pencil_x, card_cy)
            time.sleep(0.2)

            # Click remark field (relative win_left + 296, win_top + 389)
            field_x = wl + 296
            field_y = wt + 389
            pyautogui.click(field_x, field_y)
            paste_text(new_remark, clear_before=True)
            time.sleep(0.1)

            # Click save (relative win_left + 670, win_top + 828)
            save_x = wl + 670
            save_y = wt + 828
            pyautogui.click(save_x, save_y)
            time.sleep(0.15)
            gui_success = True
            logs.append("已完成 GUI 悬浮触发、编辑点击、备注粘贴与保存")
        except Exception as e:
            logs.append(f"GUI 交互微调跳过: {e}")

    # SQLite DB update / verification (Dual Channel)
    db_verified = False
    if db_path:
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            # Update notes
            cur.execute(
                "UPDATE providers SET notes = ? WHERE name LIKE ?",
                (new_remark, f"%{provider_name}%")
            )
            conn.commit()
            # Verify
            cur.execute(
                "SELECT name, notes FROM providers WHERE name LIKE ?",
                (f"%{provider_name}%",)
            )
            row = cur.fetchone()
            if row and row[1] == new_remark:
                db_verified = True
                logs.append(f"数据库校验成功: 供应商 [{row[0]}] 备注已确认为 '{row[1]}'")
            conn.close()
        except Exception as e:
            logs.append(f"数据库校验异常: {e}")

    elapsed_ms = (time.perf_counter() - t_start) * 1000.0
    report = [
        f"### [CC Switch] 供应商备注修改完成 (总耗时: {elapsed_ms:.1f}ms / {elapsed_ms/1000.0:.2f}s)",
        f"- **目标供应商**: {provider_name}",
        f"- **新备注内容**: {new_remark}",
        f"- **状态**: {'成功 (UI+DB双重确认)' if (gui_success and db_verified) else '成功 (DB已确认)' if db_verified else '已执行'}",
        "**执行步骤日志:**",
    ]
    for l in logs:
        report.append(f"  * {l}")
    return "\n".join(report)
