"""WeChat sender — send messages to a WeChat contact (UI automation).

微信没有官方 API，只能模拟 UI 操作。链路（中文安全版）：
1. switch 到微信窗口
2. Ctrl+F 搜索联系人（剪贴板粘贴中文）→ Enter 进聊天
3. 剪贴板粘贴消息 → Enter 发送

为什么用剪贴板：pyautogui.typewrite 打中文会乱码（实测"文件传输助手"变"zuu阿里延"），
中文必须走 clipboard_set + Ctrl+V。

风险说明：
- 依赖微信 PC 版 UI，微信改版可能失效
- 只支持文本消息
- 发送是真实操作，不可撤回——调用前必须确认内容
"""

from __future__ import annotations

import time


def send_wechat(contact: str, message: str) -> str:
    """Send a text message to a WeChat contact (clipboard-paste, Chinese-safe).

    contact: 联系人名字
    message: 要发送的文本
    """
    import pyautogui
    from .desktop_tools import switch_window
    from .system_tools import clipboard_set

    # 0. safety checks
    if not message.strip():
        return "[error] 消息不能为空"
    if len(message) > 500:
        return "[error] 消息太长（最多 500 字）"

    # 1. bring WeChat to front
    r = switch_window("微信")
    if r.startswith("[error]"):
        return r + "（微信没开？先 open_app('微信')）"
    time.sleep(0.6)

    # 2. search contact via Ctrl+F (clipboard-paste Chinese name)
    pyautogui.press("esc")  # clear any stuck search
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "f")
    time.sleep(0.5)
    clipboard_set(contact)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.8)

    # check search results exist before pressing enter
    from .screen_tools import _screenshot, _ocr_image
    items = _ocr_image(_screenshot())
    if contact not in " ".join(i["text"] for i in items):
        return f"[error] 搜索没找到 '{contact}'（检查名字是否正确）"

    pyautogui.press("enter")  # open first result
    time.sleep(1.0)

    # 3. paste message into input box and send
    clipboard_set(message)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.4)

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