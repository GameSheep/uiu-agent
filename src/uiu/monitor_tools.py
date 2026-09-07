"""Notification & Message Monitoring Tools — Outlook Emails & WeChat Messages.

Provides proactive detection of:
- Outlook unread emails (Sender, Subject, Received Time, Body preview) via fast native MAPI
- WeChat incoming messages & unread contact badges via UI layout analysis & OCR
- Unified notification aggregator
"""

from __future__ import annotations

import json
import time
from typing import Any


def check_outlook_emails(unread_only: bool = True, limit: int = 5, folder_name: str = "Inbox") -> str:
    """Check for new/unread emails in Outlook using Windows native COM MAPI."""
    limit = max(1, min(int(limit or 5), 20))
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            ol = win32com.client.Dispatch("Outlook.Application")
            mapi = ol.GetNamespace("MAPI")
            # 6 is olFolderInbox
            inbox = mapi.GetDefaultFolder(6)

            unread_total = inbox.UnReadItemCount
            items = inbox.Items
            # Sort newest first
            try:
                items.Sort("[ReceivedTime]", True)
            except Exception:
                pass

            if unread_only:
                try:
                    items = items.Restrict("[UnRead] = True")
                except Exception:
                    pass

            total_found = items.Count
            records = []
            for i in range(1, min(total_found + 1, limit + 1)):
                try:
                    it = items.Item(i)
                    subject = str(getattr(it, "Subject", "(无主题)"))
                    sender = str(getattr(it, "SenderName", "(未知发件人)"))
                    recv_time = str(getattr(it, "ReceivedTime", ""))
                    is_unread = bool(getattr(it, "UnRead", False))
                    body = str(getattr(it, "Body", "")).strip()[:120].replace("\n", " ")

                    records.append({
                        "index": i,
                        "sender": sender,
                        "subject": subject,
                        "time": recv_time,
                        "unread": is_unread,
                        "preview": body,
                    })
                except Exception:
                    continue

            lines = [f"### [邮件] Outlook 邮件检测 (未读总数: {unread_total})"]
            if not records:
                lines.append("当前没有符合条件的新邮件。")
            else:
                for r in records:
                    unread_mark = "[未读]" if r["unread"] else "[已读]"
                    lines.append(
                        f"- {unread_mark} **{r['subject']}** | 发件人: {r['sender']} ({r['time']})\n"
                        f"  > 摘要: {r['preview']}..."
                    )
            return "\n".join(lines)
        finally:
            pythoncom.CoUninitialize()

    except Exception as e:
        # Fallback: check if Outlook window is open
        from .window_manager import find_window
        win = find_window("outlook")
        if win:
            return f"[warning] 通过 Outlook COM 检测失败 ({e})，但检测到 Outlook 窗口正在运行 (HWND: {win['hwnd']})。"
        return f"[error] Outlook 邮件检测失败: {type(e).__name__}: {e} (请确认 Outlook 已启动并配置好邮箱)"


def check_wechat_messages(unread_only: bool = True, check_active_chat: bool = True) -> str:
    """Check WeChat desktop client for unread messages and active conversation updates."""
    from .window_manager import find_window, focus_window, open_or_focus_app, ensure_default_desktop
    ensure_default_desktop()
    from .screen_tools import _ocr_full_screen

    # 1. Bring WeChat to front and ensure top-level focus
    open_res = open_or_focus_app("微信")
    win = find_window("微信")
    if not win:
        return "[error] 未能打开或置顶微信窗口，无法检测新消息"

    focus_window(win["hwnd"])
    time.sleep(0.3)

    # Get window dimensions
    import win32gui
    rect = win32gui.GetWindowRect(win["hwnd"])
    left, top, right, bottom = rect
    win_w = right - left
    win_h = bottom - top

    if win_w < 200 or win_h < 200:
        return "[error] 微信窗口尺寸过小或已隐藏"

    # 2. OCR contact sidebar with RapidOCR for 100% accurate Chinese recognition
    from .vision_locator import get_screen_elements
    sidebar_w = min(280, max(220, int(win_w * 0.28)))
    sidebar_items = get_screen_elements(
        region=(left + 50, top + 60, sidebar_w, win_h - 60),
        engine="rapidocr",
    )

    import re
    badge_pattern = re.compile(r"^\[?[1-9]\d*\+?\]?$")
    time_pattern = re.compile(r"^(\d{1,2}[:：]\d{2}|昨天|星期[一二三四五六日]|前天)$")

    # Group sidebar items into conversation rows based on vertical proximity
    # In WeChat desktop, each conversation item has Name + Time on top, and Preview below (~20px)
    sidebar_items.sort(key=lambda x: x["cy"])

    unread_contacts = []
    conversations = []
    visited_indices = set()

    for i, it in enumerate(sidebar_items):
        if i in visited_indices:
            continue
        text = it.get("text", "").strip()
        if not text:
            continue

        # Skip standalone timestamps or search bar
        if time_pattern.match(text) or text in ("Q搜索", "搜索"):
            continue

        # Check if this item is an unread badge
        w = int(it.get("w", 0))
        h = int(it.get("h", 0))
        if badge_pattern.match(text) and 10 <= w <= 45 and 10 <= h <= 35:
            # Look for contact name close to this badge
            nearby = [
                sidebar_items[j]["text"] for j in range(len(sidebar_items))
                if j != i and abs(sidebar_items[j]["cy"] - it["cy"]) < 25
                and not badge_pattern.match(sidebar_items[j]["text"])
                and not time_pattern.match(sidebar_items[j]["text"])
            ]
            c_name = nearby[0] if nearby else "(未知联系人)"
            unread_contacts.append(f"{c_name} ({text}条未读)")
            continue

        # This item is likely a contact name
        c_name = text
        visited_indices.add(i)
        c_time = ""
        c_preview = ""

        # Find corresponding time and message preview
        for j in range(len(sidebar_items)):
            if j == i or j in visited_indices:
                continue
            other = sidebar_items[j]
            dy = other["cy"] - it["cy"]

            # Same line (time or badge)
            if abs(dy) < 12:
                o_text = other.get("text", "").strip()
                if time_pattern.match(o_text) or any(k in o_text for k in (":", "：", "星期", "昨天")):
                    c_time = o_text
                    visited_indices.add(j)
                elif badge_pattern.match(o_text) and 10 <= int(other.get("w", 0)) <= 45:
                    unread_contacts.append(f"{c_name} ({o_text}条未读)")
                    visited_indices.add(j)
            # Message preview directly below name (~15px to ~35px below)
            elif 14 <= dy <= 35 and not c_preview:
                o_text = other.get("text", "").strip()
                if not time_pattern.match(o_text) and not badge_pattern.match(o_text):
                    c_preview = o_text
                    visited_indices.add(j)

        conv_info = f"{c_name}"
        if c_time:
            conv_info += f" [{c_time}]"
        if c_preview:
            conv_info += f": {c_preview}"
        conversations.append(conv_info)

    lines = ["### [微信] 微信消息与会话检测结果"]
    if unread_contacts:
        lines.append(f"**发现未读新消息联系人 ({len(unread_contacts)} 个)**:")
        for c in unread_contacts:
            lines.append(f"- [未读] {c}")
    else:
        lines.append("- 未在会话列表中发现带未读数字的气泡。")

    if not unread_only or not unread_contacts:
        if conversations:
            lines.append(f"\n**最近会话与最新动态 (前 {min(8, len(conversations))} 项)**:")
            for item in conversations[:8]:
                lines.append(f"- {item}")

    # 3. Check active chat messages if requested
    if check_active_chat:
        chat_left = left + 50 + sidebar_w + 10
        chat_w = win_w - (sidebar_w + 70)
        chat_items = get_screen_elements(
            region=(chat_left, top + 60, chat_w, win_h - 180),
            engine="rapidocr",
        )
        if chat_items:
            chat_items.sort(key=lambda x: x["cy"])
            latest = [
                it["text"] for it in chat_items
                if it.get("text", "").strip() and not time_pattern.match(it.get("text", "").strip())
                and it.get("text", "").strip() != "0"
            ]
            if latest:
                lines.append("\n**当前打开会话的最近消息记录**:")
                for m in latest[-8:]:
                    lines.append(f"- {m}")

    return "\n".join(lines)


def check_notifications(target: str = "all") -> str:
    """Unified check for incoming notifications across Outlook and WeChat.

    target: 'all' | 'outlook' | 'wechat'
    """
    target = (target or "all").lower().strip()
    results = []

    if target in ("all", "outlook", "mail", "email"):
        results.append(check_outlook_emails(unread_only=True, limit=5))

    if target in ("all", "wechat", "weixin", "wx"):
        results.append(check_wechat_messages(unread_only=True, check_active_chat=True))

    return "\n\n---\n\n".join(results) if results else f"[error] 不支持的检测目标: {target}"


# Tool schemas
CHECK_OUTLOOK_EMAILS_DEF = {
    "type": "function",
    "function": {
        "name": "check_outlook_emails",
        "description": "检测 Outlook 邮箱中的最新未读邮件，返回发件人、主题、接收时间和正文摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "unread_only": {"type": "boolean", "description": "是否只看未读邮件（默认 True）", "default": True},
                "limit": {"type": "integer", "description": "最多获取几封邮件（默认 5）", "default": 5},
            },
        },
    },
}

CHECK_WECHAT_MESSAGES_DEF = {
    "type": "function",
    "function": {
        "name": "check_wechat_messages",
        "description": "检测桌面微信的新消息，自动识别未读红点联系人及当前聊天窗口的最新消息内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "unread_only": {"type": "boolean", "description": "是否重点检查未读联系人（默认 True）", "default": True},
                "check_active_chat": {"type": "boolean", "description": "是否读取当前打开会话的最新聊天内容（默认 True）", "default": True},
            },
        },
    },
}

CHECK_NOTIFICATIONS_DEF = {
    "type": "function",
    "function": {
        "name": "check_notifications",
        "description": "综合检测系统通知与消息（支持一键检查 Outlook 邮件、微信新消息）。",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["all", "outlook", "wechat"], "default": "all", "description": "检测目标：'all'（全部）、'outlook'（邮件）、'wechat'（微信）"},
            },
        },
    },
}

MONITOR_TOOLS: dict[str, dict] = {
    "check_outlook_emails": {"def": CHECK_OUTLOOK_EMAILS_DEF, "fn": check_outlook_emails},
    "check_wechat_messages": {"def": CHECK_WECHAT_MESSAGES_DEF, "fn": check_wechat_messages},
    "check_notifications": {"def": CHECK_NOTIFICATIONS_DEF, "fn": check_notifications},
}


def monitor_tool_defs() -> list[dict]:
    return [t["def"] for t in MONITOR_TOOLS.values()]
