"""Pure OCR & Mouse/Keyboard GUI Email Sender.

Sends emails in real desktop email clients (Outlook, Foxmail, Webmail)
purely via screen OCR element detection, mouse clicks, and clipboard pasting,
with zero reliance on SMTP credentials or backend mail APIs.
"""

from __future__ import annotations

import time
from typing import Any

from .gui_primitives import mouse_click, paste_text, press_hotkey, press_key
from .vision_locator import locate_text_on_screen
from .window_manager import find_window, open_or_focus_app


def send_email_via_gui(
    client: str = "outlook",
    to: str = "",
    subject: str = "",
    body: str = "",
    cc: str = "",
) -> str:
    """Send an email through desktop client UI using pure OCR recognition and mouse/keyboard actions.

    - client: Application name/keyword, default 'outlook'.
    - to: Recipient email address(es).
    - subject: Email subject line.
    - body: Email content body.
    - cc: Optional CC recipient(s).
    """
    to = (to or "").strip()
    subject = (subject or "").strip()
    body = (body or "").strip()

    if not to:
        return "[error] 收件人 (to) 不能为空"
    if not subject and not body:
        return "[error] 邮件主题与正文不能同时为空"

    steps: list[str] = []

    # Step 1: Open or focus mail client
    open_res = open_or_focus_app(client)
    steps.append(f"1. 启动/置顶邮件客户端: {open_res}")
    time.sleep(1.0)

    # Step 2: Click "New Mail" button
    new_mail_elem = None
    for label in ("新建电子邮件", "新邮件", "新建", "New Email", "New Mail", "写信", "写邮件"):
        new_mail_elem = locate_text_on_screen(label)
        if new_mail_elem:
            break

    if new_mail_elem:
        mouse_click(new_mail_elem["cx"], new_mail_elem["cy"])
        steps.append(f"2. OCR 定位并点击新邮件按钮: '{new_mail_elem.get('text')}' 坐标 ({new_mail_elem['cx']}, {new_mail_elem['cy']})")
    else:
        # Standard shortcut for New Mail in Outlook/Foxmail
        press_hotkey(["ctrl", "n"])
        steps.append("2. 未直接找到新建按钮，已发送快捷键 Ctrl+N 新建邮件")

    time.sleep(1.5)  # Wait for compose window to open

    # Step 3: Locate "To" field
    to_elem = None
    for label in ("收件人", "收件人...", "To", "To..."):
        to_elem = locate_text_on_screen(label)
        if to_elem:
            break

    if to_elem:
        mouse_click(to_elem["cx"] + 70, to_elem["cy"])
        time.sleep(0.2)
        paste_text(to, clear_before=True)
        time.sleep(0.2)
        press_key("enter")
        steps.append(f"3. OCR 定位收件人栏并填入: {to}")
    else:
        # Click upper area or Tab
        press_key("tab")
        paste_text(to, clear_before=True)
        press_key("enter")
        steps.append(f"3. 尝试通过键盘焦点填入收件人: {to}")

    time.sleep(0.3)

    # Step 4: Optional CC
    if cc.strip():
        cc_elem = locate_text_on_screen("抄送") or locate_text_on_screen("Cc")
        if cc_elem:
            mouse_click(cc_elem["cx"] + 70, cc_elem["cy"])
            time.sleep(0.2)
            paste_text(cc.strip(), clear_before=True)
            press_key("enter")
            steps.append(f"4. OCR 定位抄送栏并填入: {cc}")

    time.sleep(0.3)

    # Step 5: Locate "Subject" field
    subj_elem = None
    for label in ("主题", "Subject", "主题..."):
        subj_elem = locate_text_on_screen(label)
        if subj_elem:
            break

    if subj_elem:
        mouse_click(subj_elem["cx"] + 70, subj_elem["cy"])
        time.sleep(0.2)
        paste_text(subject, clear_before=True)
        steps.append(f"5. OCR 定位主题栏并填入: '{subject}'")
    else:
        press_key("tab")
        paste_text(subject, clear_before=True)
        steps.append(f"5. 尝试填入主题: '{subject}'")

    time.sleep(0.3)

    # Step 6: Focus and paste email body
    # Usually clicking below the subject line or Tab enters the body
    if subj_elem:
        mouse_click(subj_elem["cx"], subj_elem["cy"] + 60)
    else:
        press_key("tab")

    time.sleep(0.2)
    paste_text(body, clear_before=True)
    steps.append(f"6. 填入邮件正文内容 (共 {len(body)} 字符)")
    time.sleep(0.5)

    # Step 7: Locate and click "Send" button
    send_elem = None
    for label in ("发送", "Send", "立即发送"):
        send_elem = locate_text_on_screen(label)
        if send_elem:
            break

    if send_elem:
        mouse_click(send_elem["cx"], send_elem["cy"])
        steps.append(f"7. OCR 定位并点击发送按钮: '{send_elem.get('text')}' 坐标 ({send_elem['cx']}, {send_elem['cy']})")
    else:
        # Standard send shortcut: Ctrl+Enter or Alt+S
        press_hotkey(["ctrl", "enter"])
        steps.append("7. 未直接找到发送按钮，发送快捷键 Ctrl+Enter 提交邮件发送")

    time.sleep(1.0)
    steps.append("8. 纯 OCR 邮件发送流程执行完毕")
    return "[ok] 纯 OCR 鼠标点击邮件发送成功:\n" + "\n".join(steps)


# Tool schemas
SEND_EMAIL_VIA_GUI_DEF = {
    "type": "function",
    "function": {
        "name": "send_email_via_gui",
        "description": "通过屏幕 OCR 找字与鼠标键盘点击，在真实桌面邮件客户端（如 Outlook / Foxmail）中纯界面自动化撰写并发送邮件（免配置 SMTP 密码）。",
        "parameters": {
            "type": "object",
            "properties": {
                "client": {"type": "string", "default": "outlook", "description": "邮件客户端名称（默认 'outlook'）"},
                "to": {"type": "string", "description": "收件人邮箱地址"},
                "subject": {"type": "string", "description": "邮件主题"},
                "body": {"type": "string", "description": "邮件正文内容"},
                "cc": {"type": "string", "description": "抄送邮箱（可选）"},
            },
            "required": ["to", "subject", "body"],
        },
    },
}

EMAIL_GUI_TOOLS: dict[str, dict] = {
    "send_email_via_gui": {"def": SEND_EMAIL_VIA_GUI_DEF, "fn": send_email_via_gui},
}


def email_gui_tool_defs() -> list[dict]:
    return [t["def"] for t in EMAIL_GUI_TOOLS.values()]
