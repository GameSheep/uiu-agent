"""Universal Window & Process Manager."""

from __future__ import annotations

import os
import time


def list_visible_windows() -> list[dict]:
    import win32gui
    import win32process

    windows = []

    def _enum_callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip()
        if not title:
            return
        rect = win32gui.GetWindowRect(hwnd)
        if (rect[2] - rect[0]) <= 10 or (rect[3] - rect[1]) <= 10:
            return

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        windows.append({
            "hwnd": hwnd,
            "title": title,
            "pid": pid,
            "rect": rect,
            "is_minimized": bool(win32gui.IsIconic(hwnd))
        })

    win32gui.EnumWindows(_enum_callback, None)
    return windows


def find_window(title_keyword: str) -> dict | None:
    keyword = title_keyword.lower().strip()
    for win in list_visible_windows():
        if keyword in win["title"].lower():
            return win
    return None


def focus_window(hwnd: int) -> str:
    import win32api
    import win32con
    import win32gui
    import win32process

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        time.sleep(0.1)

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

        time.sleep(0.2)
        return f"[ok] 窗口 {hwnd} 已置顶前台"
    except Exception as e:
        return f"[error] 激活窗口失败: {type(e).__name__}: {e}"


def set_window_state(hwnd: int, action: str) -> str:
    import win32con
    import win32gui

    action = action.lower().strip()
    action_map = {
        "maximize": win32con.SW_MAXIMIZE,
        "minimize": win32con.SW_MINIMIZE,
        "restore": win32con.SW_RESTORE,
    }

    try:
        if action == "close":
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return f"[ok] 已发送关闭指令到窗口 {hwnd}"
        if action in action_map:
            win32gui.ShowWindow(hwnd, action_map[action])
            time.sleep(0.2)
            return f"[ok] 窗口 {hwnd} 状态已设为 {action}"
        return f"[error] 不支持的操作类型: {action}"
    except Exception as e:
        return f"[error] 调整窗口状态失败: {type(e).__name__}: {e}"


# Shell 元字符：出现任何一个即拒绝（防注入，不经过 shell）
_SHELL_META = set("&|<>^`$(){};\"'\\\n\r\t")


def launch_application(target: str) -> str:
    """Launch a program / open a file / open a URL. No shell involved.

    Validation: non-empty, length-bounded, no shell metacharacters; URLs must
    use an http(s) scheme (mirrors open_url's guardrail).
    """
    target = (target or "").strip()
    if not target:
        return "[error] target 不能为空"
    if len(target) > 2000:
        return "[error] target 过长"
    if any(ch in _SHELL_META for ch in target):
        return "[error] target 含非法字符（shell 元字符），已拒绝"
    low = target.lower()
    if low.startswith(("javascript:", "data:", "vbscript:", "file:", "about:")):
        return "[error] 不支持的 URL scheme（仅 http/https）"
    try:
        os.startfile(target)
        time.sleep(0.8)
        return f"[ok] 启动命令已触发: {target}"
    except OSError:
        return f"[error] 启动应用失败: 无法打开 {target!r}"
    except Exception as e:
        return f"[error] 启动应用失败: {type(e).__name__}: {e}"