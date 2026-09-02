"""WeChat sender — send messages to a WeChat contact (UI automation).

微信没有官方 API，只能模拟 UI 操作。链路：
1. switch 到微信窗口
2. 在聊天列表 OCR 找联系人 → 点击进入
3. 用窗口几何定位输入框（微信聊天窗口底部是输入区，固定布局）
4. 点击输入框 → type_text 输入 → 按 Enter 发送

风险说明：
- 依赖微信 PC 版 UI 布局（底部输入框），微信改版可能失效
- 只支持文本消息
- 发送是真实操作，不可撤回——调用前必须确认内容
"""

from __future__ import annotations

import time


def send_wechat(contact: str, message: str) -> str:
    """Send a text message to a WeChat contact.

    contact: 联系人名字（聊天列表里可见的）
    message: 要发送的文本
    """
    import pyautogui
    from .desktop_tools import switch_window, list_windows, get_foreground_window, _desktop_path
    from .screen_tools import _screenshot, _ocr_image, _find

    # 0. safety: message must be non-empty and short-ish
    if not message.strip():
        return "[error] 消息不能为空"
    if len(message) > 500:
        return "[error] 消息太长（最多 500 字）"

    # 1. bring WeChat to front
    r = switch_window("微信")
    if r.startswith("[error]"):
        return r + "（微信没开？先 open_app('微信')）"
    time.sleep(0.6)

    # 2. find contact in the chat list (left panel) and click it
    path = _screenshot()
    items = _ocr_image(path)
    matches = _find(items, contact)
    if not matches:
        # maybe need to scroll the list / search
        cands = [i["text"] for i in items if len(i["text"]) <= 12][:10]
        return f"[error] 聊天列表没找到 '{contact}'。可见的: {cands}"

    # click the contact (prefer one in left panel: x < 400)
    left_matches = [m for m in matches if m["x"] < 400]
    target = (left_matches or matches)[0]
    cx, cy = int(target["cx"]), int(target["cy"])
    pyautogui.moveTo(cx, cy, duration=0.15)
    pyautogui.click()
    time.sleep(0.5)

    # 3. locate input box via window geometry.
    #    WeChat chat input is at the bottom of the chat area, ~50px above the
    #    bottom of the message panel. We use the window rect of WeChat.
    hwnd = _wechat_hwnd()
    if hwnd is None:
        return "[error] 找不到微信窗口（可能被最小化）"
    win32gui, _, _ = _wechat_win32()
    rect = win32gui.GetWindowRect(hwnd)
    # input box: near bottom of window, roughly 1/2 to 2/3 width
    win_w = rect[2] - rect[0]
    win_h = rect[3] - rect[1]
    input_x = rect[0] + int(win_w * 0.5)
    input_y = rect[3] - int(win_h * 0.12)  # bottom ~12%
    pyautogui.moveTo(input_x, input_y, duration=0.15)
    pyautogui.click()
    time.sleep(0.3)

    # 4. type + send
    pyautogui.typewrite(message, interval=0.005)
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.3)

    return f"[ok] 已给 {contact} 发送: {message[:40]}{'…' if len(message) > 40 else ''}"


def _wechat_hwnd():
    """Find WeChat main window handle — prefer visible, non-minimized."""
    try:
        import win32gui
    except ImportError:
        return None
    candidates = []

    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t.strip() == "微信":
                candidates.append(hwnd)

    win32gui.EnumWindows(_enum, None)
    if not candidates:
        return None
    # prefer non-minimized, visible-on-screen window
    for h in candidates:
        if not win32gui.IsIconic(h) and win32gui.GetWindowRect(h)[0] > -1000:
            return h
    # fallback: any (will need restore)
    return candidates[0]


def _wechat_win32():
    import win32gui, win32con, win32api
    return win32gui, win32con, win32api


# tool definition

SEND_WECHAT_DEF = {
    "type": "function",
    "function": {
        "name": "send_wechat",
        "description": "给指定的微信联系人发文本消息。**危险操作，发送不可撤回**——调用前必须跟用户确认联系人和消息内容！",
        "parameters": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "微信联系人名字"},
                "message": {"type": "string", "description": "要发送的消息文本（最多500字）"},
            },
            "required": ["contact", "message"],
        },
    },
}

WECHAT_TOOLS: dict[str, dict] = {
    "send_wechat": {"def": SEND_WECHAT_DEF, "fn": send_wechat},
}


def wechat_tool_defs() -> list[dict]:
    return [t["def"] for t in WECHAT_TOOLS.values()]


def call_wechat_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in WECHAT_TOOLS:
        return f"[error] unknown wechat tool: {name}"
    fn = WECHAT_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"