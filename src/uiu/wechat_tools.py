"""WeChat Tools — 8-Step Closed-Loop Sender.

微信专用语义级闭环自动化：置顶 -> OCR 定位 -> 点击 -> 标题验证 -> 粘贴 -> 输入区验证 -> 发送 -> 结果核验。
"""

from __future__ import annotations

import ctypes
import time

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def find_window_by_title(title_keyword: str) -> int | None:
    try:
        import win32gui
    except ImportError:
        return None

    matched = None

    def _enum(hwnd, _):
        nonlocal matched
        if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
            text = win32gui.GetWindowText(hwnd)
            if title_keyword in text:
                matched = hwnd

    win32gui.EnumWindows(_enum, None)
    return matched


def activate_window(hwnd: int) -> bool:
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    time.sleep(0.15)

    try:
        fg = win32gui.GetForegroundWindow()
        cur_tid = win32api.GetCurrentThreadId()
        fg_tid, _ = win32process.GetWindowThreadProcessId(int(fg or 0))
        target_tid, _ = win32process.GetWindowThreadProcessId(int(hwnd))

        attached = []
        for tid in (fg_tid, target_tid):
            if tid and win32process.AttachThreadInput(cur_tid, tid, True):
                attached.append(tid)

        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for tid in attached:
                try:
                    win32process.AttachThreadInput(cur_tid, tid, False)
                except Exception:
                    pass
    except Exception:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass

    time.sleep(0.25)
    return win32gui.GetForegroundWindow() == hwnd


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import win32gui
    return win32gui.GetWindowRect(hwnd)


def click_point(x: int, y: int, clicks: int = 1, button: str = "left", delay: float = 0.2):
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click(x, y, clicks=clicks, button=button)
    time.sleep(delay)


def input_text(text: str):
    import pyautogui
    from .system_tools import clipboard_set

    clipboard_set(text)
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.25)


def find_in_items(items: list[dict], needle: str, exact: bool = False) -> dict | None:
    needle = needle.strip()
    if not needle:
        return None
    matches = []
    for it in items:
        t = it.get("text", "").strip()
        if not t:
            continue
        if exact and t == needle:
            return it
        if not exact and (needle in t or t in needle):
            matches.append(it)
    if matches:
        return min(matches, key=lambda i: abs(len(i.get("text", "")) - len(needle)))
    return None


def filter_by_zone(items: list[dict], left: int, top: int, right: int, bottom: int) -> list[dict]:
    return [
        it for it in items
        if left <= it.get("cx", -1) <= right and top <= it.get("cy", -1) <= bottom
    ]


def execute_8step_send(window_title: str, target_name: str, message: str) -> str:
    import pyautogui
    from .screen_tools import _ocr_full_screen

    trace: list[str] = []

    def _log(s: str):
        trace.append(s)

    target_name = (target_name or "").strip()
    message = (message or "").strip()

    if not target_name or not message:
        return "[error] 目标条目或发送消息不能为空"

    # S1: 置顶
    hwnd = find_window_by_title(window_title)
    if not hwnd:
        return f"[error] S1 未找到包含 '{window_title}' 的活动窗口"
    if not activate_window(hwnd):
        return f"[error] S1 无法将 '{window_title}' 置顶到前台"

    left, top, right, bottom = get_window_rect(hwnd)
    w, h = right - left, bottom - top
    if w <= 100 or h <= 100:
        return "[error] S1 窗口尺寸异常（可能已最小化）"
    _log(f"S1 ok 窗口置顶成功 rect=({left},{top},{right},{bottom})")

    def _get_win_ocr():
        time.sleep(0.3)
        return [it for it in _ocr_full_screen() if left <= it.get("cx", -1) <= right and top <= it.get("cy", -1) <= bottom]

    # S2: 定位左侧目标
    items_s2 = _get_win_ocr()
    list_items = filter_by_zone(items_s2, left, top, int(left + w * 0.42), bottom)
    matched_target = find_in_items(list_items, target_name)
    if not matched_target:
        return f"[error] S2 在左侧列表未看到 '{target_name}'\n" + "\n".join(trace)

    target_cx = matched_target["cx"]
    target_cy = matched_target["cy"]
    _log(f"S2 ok 定位到 '{target_name}' 坐标=({target_cx}, {target_cy})")

    # S3: 物理点击
    click_point(target_cx, target_cy, clicks=1)
    time.sleep(0.5)
    _log("S3 ok 已点击目标条目")

    # S4: 校验标题
    items_s4 = _get_win_ocr()
    title_zone = filter_by_zone(items_s4, int(left + w * 0.35), top, int(right - w * 0.1), int(top + h * 0.15))
    if not find_in_items(title_zone, target_name):
        _log("S4 标题未更新，重试补点一次")
        click_point(target_cx, target_cy, clicks=1)
        time.sleep(0.5)
        items_s4 = _get_win_ocr()
        title_zone = filter_by_zone(items_s4, int(left + w * 0.35), top, int(right - w * 0.1), int(top + h * 0.15))
        if not find_in_items(title_zone, target_name):
            return f"[error] S4 标题栏未变为 '{target_name}'\n" + "\n".join(trace)
    _log(f"S4 ok 标题确认为 '{target_name}'")

    # S5: 聚焦输入框并粘贴
    input_x = int(left + w * 0.70)
    input_y = int(top + h * 0.85)
    click_point(input_x, input_y, clicks=1)
    time.sleep(0.2)
    input_text(message)
    _log(f"S5 ok 已在坐标 ({input_x}, {input_y}) 粘贴内容")

    # S6: 校验输入区
    items_s6 = _get_win_ocr()
    input_zone = filter_by_zone(items_s6, int(left + w * 0.35), int(top + h * 0.70), right, bottom)
    msg_key = message[:8]
    if not find_in_items(input_zone, msg_key):
        input_y_alt = int(top + h * 0.78)
        click_point(input_x, input_y_alt, clicks=1)
        time.sleep(0.15)
        input_text(message)
        time.sleep(0.3)
        items_s6 = _get_win_ocr()
        input_zone = filter_by_zone(items_s6, int(left + w * 0.35), int(top + h * 0.65), right, bottom)
        if not find_in_items(input_zone, msg_key):
            return f"[error] S6 内容未能成功填入输入框\n" + "\n".join(trace)
    _log("S6 ok 输入区验证成功")

    # S7: 发送
    pyautogui.press("enter")
    time.sleep(0.6)
    _log("S7 ok 已按 Enter 发送")

    # S8: 校验聊天记录区
    items_s8 = _get_win_ocr()
    chat_zone = filter_by_zone(items_s8, int(left + w * 0.35), int(top + h * 0.15), right, int(top + h * 0.75))
    if find_in_items(chat_zone, msg_key):
        _log("S8 ok 聊天区已检测到发送内容")
        return f"[ok] 成功向 '{target_name}' 发送消息: {message[:30]}\n" + "\n".join(trace)
    else:
        if not find_in_items(input_zone, msg_key):
            _log("S8 info 输入框已清空")
            return f"[ok] 已发送（输入框已空）: {message[:30]}\n" + "\n".join(trace)
        return f"[error] S8 聊天区未见消息，可能发送失败\n" + "\n".join(trace)


def send_wechat(contact: str, message: str) -> str:
    return execute_8step_send(window_title="微信", target_name=contact, message=message)


SEND_WECHAT_DEF = {
    "type": "function",
    "function": {
        "name": "send_wechat",
        "description": "微信专属 8 步语义闭环发消息工具：置顶→定位联系人→点击→核对标题→聚焦输入区→核对输入文字→回车发送→核对上屏。有严密校验防误发。",
        "parameters": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "微信联系人或群聊名称"},
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