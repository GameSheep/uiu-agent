"""Windows desktop control tools — window switching, taskbar, hotkeys.

能力（agent 可通过自然语言调用）：
- list_windows    列出所有打开的窗口
- switch_window   按标题切换到某窗口（前/后台）
- close_window    关闭指定窗口
- window_action   最小化/最大化/还原窗口
- run_hotkey      执行系统快捷键（Win+D 等）
- taskbar_click   点任务栏程序（按名字 OCR 定位）
- focus_input     聚焦输入（点窗口中心）

依赖：pyautogui（键鼠）+ pywin32（Windows 窗口 API）
"""

from __future__ import annotations

import re
import time
from pathlib import Path


# ---------- windows (pywin32) ----------

def _win32():
    """Lazy-import pywin32 (Windows only)."""
    import win32gui
    import win32con
    import win32api
    return win32gui, win32con, win32api


def _window_title(hwnd) -> str:
    try:
        win32gui, _, _ = _win32()
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def list_windows() -> str:
    """List all visible top-level windows with their titles."""
    win32gui, _, _ = _win32()
    windows = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = _window_title(hwnd)
        if title.strip():
            windows.append((hwnd, title))

    win32gui.EnumWindows(_enum, None)
    if not windows:
        return "(没有可见窗口)"
    lines = []
    for i, (hwnd, title) in enumerate(windows, 1):
        lines.append(f"  {i}. {title[:60]}")
    return f"打开的窗口 ({len(windows)}):\n" + "\n".join(lines)


def _find_window(title_query: str):
    """Find a window whose title contains the query. Returns hwnd or None."""
    win32gui, _, _ = _win32()
    best = None
    for hwnd in _all_hwnds():
        t = _window_title(hwnd)
        if title_query.lower() in t.lower():
            # prefer exact-ish (shorter title = closer match)
            if best is None or len(t) < len(_window_title(best)):
                best = hwnd
    return best


def _all_hwnds():
    win32gui, _, _ = _win32()
    out = []
    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            out.append(hwnd)
    win32gui.EnumWindows(_enum, None)
    return out


def switch_window(title_query: str, background: bool = False) -> str:
    """Switch to a window by title (bring to front / focus)."""
    hwnd = _find_window(title_query)
    if hwnd is None:
        return f"[error] 没找到窗口包含 '{title_query}'（先 list_windows 看看有什么）"
    win32gui, win32con, win32api = _win32()
    try:
        if win32gui.IsIconic(hwnd):  # minimized → restore
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if not background:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            # Windows foreground-lock: simulating an Alt keypress releases it,
            # letting us bring the target to front reliably.
            try:
                win32api.keybd_event(0x12, 0, 0, 0)      # Alt down
                win32api.keybd_event(0x12, 0, 2, 0)      # Alt up
            except Exception:
                pass
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.2)
        return f"[ok] 已切换到窗口: {_window_title(hwnd)[:50]}"
    except Exception as e:
        # fallback: use ShowWindow only (activate without stealing focus reliably)
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            return f"[ok] 已激活窗口(后台): {_window_title(hwnd)[:50]}"
        except Exception:
            return f"[error] 切换失败: {type(e).__name__}: {e}"


def window_action(title_query: str, action: str) -> str:
    """minimize / maximize / restore / close a window by title."""
    hwnd = _find_window(title_query)
    if hwnd is None:
        return f"[error] 没找到窗口包含 '{title_query}'"
    win32gui, win32con, _ = _win32()
    action = action.lower()
    try:
        if action in ("minimize", "最小化"):
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        elif action in ("maximize", "最大化"):
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif action in ("restore", "还原"):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        elif action in ("close", "关闭"):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        else:
            return f"[error] 未知操作: {action}（minimize/maximize/restore/close）"
        return f"[ok] {action} '{_window_title(hwnd)[:40]}'"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def get_foreground_window() -> str:
    """Return the currently focused window title."""
    win32gui, _, _ = _win32()
    hwnd = win32gui.GetForegroundWindow()
    title = _window_title(hwnd)
    return f"当前前台窗口: {title or '(无标题)'}"


# ---------- hotkeys (pyautogui) ----------

# Windows 常用快捷键映射
_HOTKEYS = {
    "win+d": ["win", "d"],
    "win+m": ["win", "m"],           # 最小化所有窗口
    "win+e": ["win", "e"],           # 文件资源管理器
    "win+l": ["win", "l"],           # 锁屏
    "win+tab": ["win", "tab"],       # 任务视图
    "alt+tab": ["alt", "tab"],       # 切换窗口
    "ctrl+alt+delete": ["ctrl", "alt", "delete"],
    "ctrl+c": ["ctrl", "c"],
    "ctrl+v": ["ctrl", "v"],
    "ctrl+z": ["ctrl", "z"],
    "ctrl+y": ["ctrl", "y"],
    "ctrl+s": ["ctrl", "s"],
    "ctrl+a": ["ctrl", "a"],
    "ctrl+f": ["ctrl", "f"],
    "alt+f4": ["alt", "f4"],         # 关闭当前窗口
    "win+shift+s": ["win", "shift", "s"],  # 截图
    "win+left": ["win", "left"],     # 窗口贴左
    "win+right": ["win", "right"],   # 窗口贴右
    "win+up": ["win", "up"],         # 最大化
    "win+down": ["win", "down"],     # 还原/最小化
    "win+i": ["win", "i"],           # 设置
    "win+r": ["win", "r"],           # 运行
    "win+s": ["win", "s"],           # 搜索
    "f5": ["f5"],                    # 刷新
    "enter": ["enter"],
    "esc": ["esc"],
    "tab": ["tab"],
    "space": ["space"],
    "backspace": ["backspace"],
    "delete": ["delete"],
}


def run_hotkey(hotkey: str) -> str:
    """Execute a hotkey (e.g. 'win+d', 'ctrl+c', 'alt+tab')."""
    import pyautogui
    key = hotkey.lower().strip()
    combo = _HOTKEYS.get(key)
    if combo is None:
        # try to parse custom combo like ctrl+shift+n
        parts = key.split("+")
        mapped = []
        for p in parts:
            p = p.strip()
            if p in ("win", "windows"):
                mapped.append("win")
            elif p in ("ctrl", "control"):
                mapped.append("ctrl")
            elif p in ("shift",):
                mapped.append("shift")
            elif p in ("alt",):
                mapped.append("alt")
            else:
                mapped.append(p)
        combo = mapped
    try:
        if len(combo) > 1:
            pyautogui.hotkey(*combo)
        else:
            pyautogui.press(combo[0])
        return f"[ok] 已执行 {hotkey}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def taskbar_click(app_name: str) -> str:
    """Click a taskbar app by its name (OCR the taskbar strip).

    截图任务栏区域 → OCR 找应用名 → 点击。
    """
    import pyautogui
    from .screen_tools import _ocr_image
    import tempfile
    from pathlib import Path

    # screenshot only the taskbar (bottom strip, ~48px tall)
    screen_w, screen_h = pyautogui.size()
    taskbar_h = 48
    region = (0, screen_h - taskbar_h, screen_w, taskbar_h)
    img = pyautogui.screenshot(region=region)
    path = str(Path(tempfile.gettempdir()) / "uiu_taskbar.png")
    img.save(path)
    items = _ocr_image(path)
    if not items:
        return "(任务栏没识别到文字)"

    # find app name
    matches = [i for i in items if app_name.lower() in i["text"].lower()]
    if not matches:
        cands = [i["text"] for i in items][:12]
        return f"[error] 任务栏没找到 '{app_name}'。任务栏文字: {cands}"
    best = max(matches, key=lambda i: i["score"])
    # taskbar icon is a bit above text center (icons row is above labels)
    abs_x = int(best["cx"])
    abs_y = int(screen_h - taskbar_h + best["cy"] - 8)  # click the icon, slightly above text
    pyautogui.moveTo(abs_x, abs_y, duration=0.2)
    pyautogui.click()
    return f"[ok] 已点击任务栏 '{best['text']}' ({abs_x},{abs_y})"


def focus_input() -> str:
    """Click the center of the foreground window to focus it for typing."""
    import pyautogui
    hwnd = _foreground_hwnd()
    win32gui, _, _ = _win32()
    try:
        rect = win32gui.GetWindowRect(hwnd)
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        pyautogui.click(cx, cy)
        return f"[ok] 已聚焦前台窗口 ({cx},{cy})"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def _foreground_hwnd():
    win32gui, _, _ = _win32()
    return win32gui.GetForegroundWindow()


# ---------- scroll (for long lists / chat history) ----------

def scroll(direction: str = "down", amount: int = 3) -> str:
    """Scroll the current window. direction: down/up, amount: 滚轮格数.

    微信聊天记录、长列表、网页长页面的核心工具。多滚几次看更多内容。
    """
    import pyautogui
    direction = direction.lower()
    clicks = max(1, min(amount, 20))
    if direction in ("down", "下"):
        pyautogui.scroll(-clicks)
    elif direction in ("up", "上"):
        pyautogui.scroll(clicks)
    else:
        return f"[error] 方向: down/up"
    return f"[ok] 已向下滚动 {clicks} 格" if direction in ("down", "下") else f"[ok] 已向上滚动 {clicks} 格"


def open_app(app_name: str) -> str:
    """Launch an app by name (uses Windows 'start' / search). E.g. '微信', 'excel', 'notepad'.

    Tries: start <name> (shell), then common paths.
    """
    import subprocess
    # try start command (uses Windows app search / file association)
    for cmd in (
        ["cmd", "/c", "start", "", app_name],
        ["cmd", "/c", "start", app_name],
    ):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            if r.returncode == 0:
                return f"[ok] 已启动 {app_name}（等 1-2 秒窗口出现）"
        except Exception:
            continue
    return f"[error] 无法启动 {app_name}（可尝试 shell_exec 用完整路径）"


def _desktop_path() -> Path:
    """Resolve the real Desktop path (handles OneDrive redirection)."""
    # 1. try registry (shell folders)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            val, _ = winreg.QueryValueEx(k, "Desktop")
            p = Path(val)
            if p.is_dir():
                return p
    except Exception:
        pass
    # 2. fallback: common locations
    home = Path.home()
    for cand in (home / "Desktop", home / "桌面", home / "OneDrive" / "Desktop", home / "OneDrive" / "桌面"):
        if cand.is_dir():
            return cand
    return home


def list_files(path: str = "") -> str:
    """List files in a directory (default: Desktop). Useful to find files like excel."""
    import os
    if not path:
        path = str(_desktop_path())
    p = Path(path)
    if not p.is_dir():
        return f"[error] 目录不存在: {path}"
    items = []
    for entry in sorted(p.iterdir()):
        kind = "📁" if entry.is_dir() else "📄"
        try:
            size = entry.stat().st_size if entry.is_file() else 0
            size_s = f" {size//1024}KB" if size > 1024 else ""
        except Exception:
            size_s = ""
        items.append(f"  {kind} {entry.name}{size_s}")
    if not items:
        return f"({path} 是空的)"
    return f"{path}:\n" + "\n".join(items[:40])


# ---------- tool definitions ----------

LIST_WINDOWS_DEF = {
    "type": "function",
    "function": {
        "name": "list_windows",
        "description": "列出所有打开的窗口标题。用户问'现在开着什么'或要切换窗口时先调用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

SWITCH_WINDOW_DEF = {
    "type": "function",
    "function": {
        "name": "switch_window",
        "description": "切换到标题包含指定文字的窗口（如'切到浏览器'）。可前台激活。",
        "parameters": {
            "type": "object",
            "properties": {
                "title_query": {"type": "string", "description": "窗口标题关键词"},
                "background": {"type": "boolean", "description": "是否只在后台切换不抢焦点"},
            },
            "required": ["title_query"],
        },
    },
}

WINDOW_ACTION_DEF = {
    "type": "function",
    "function": {
        "name": "window_action",
        "description": "对窗口执行操作：minimize/maximize/restore/close（最小化/最大化/还原/关闭）。",
        "parameters": {
            "type": "object",
            "properties": {
                "title_query": {"type": "string"},
                "action": {"type": "string", "enum": ["minimize", "maximize", "restore", "close"]},
            },
            "required": ["title_query", "action"],
        },
    },
}

RUN_HOTKEY_DEF = {
    "type": "function",
    "function": {
        "name": "run_hotkey",
        "description": "执行系统快捷键。常用：win+d(显示桌面), win+e(资源管理器), alt+tab(切换窗口), ctrl+c/v/z, alt+f4(关闭窗口), win+shift+s(截图), win+l(锁屏)。",
        "parameters": {
            "type": "object",
            "properties": {"hotkey": {"type": "string", "description": "如 'win+d'、'ctrl+s'、'alt+tab'"}},
            "required": ["hotkey"],
        },
    },
}

TASKBAR_CLICK_DEF = {
    "type": "function",
    "function": {
        "name": "taskbar_click",
        "description": "点击 Windows 任务栏上的程序图标（按应用名 OCR 定位）。如'点任务栏的微信'。",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string", "description": "任务栏上的应用名"}},
            "required": ["app_name"],
        },
    },
}

GET_FOREGROUND_DEF = {
    "type": "function",
    "function": {
        "name": "get_foreground_window",
        "description": "获取当前前台窗口的标题。操作前确认当前在哪个窗口时用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

FOCUS_INPUT_DEF = {
    "type": "function",
    "function": {
        "name": "focus_input",
        "description": "点击当前前台窗口的中心，确保输入焦点在它上面（输入前用）。",
        "parameters": {"type": "object", "properties": {}},
    },
}

SCROLL_DEF = {
    "type": "function",
    "function": {
        "name": "scroll",
        "description": "滚动当前窗口（滚轮）。微信聊天记录、长列表、网页长页面必用。要连续看更多内容就多滚几次。",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["down", "up"], "description": "向下/向上滚动"},
                "amount": {"type": "integer", "description": "滚轮格数（默认3，最多20）"},
            },
        },
    },
}

OPEN_APP_DEF = {
    "type": "function",
    "function": {
        "name": "open_app",
        "description": "启动应用/程序（按名字，如'微信'、'notepad'、'excel'）。窗口还没打开时用。",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
            "required": ["app_name"],
        },
    },
}

LIST_FILES_DEF = {
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "列出目录里的文件（默认桌面）。找文件（如 excel、文档）时用。",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径，默认桌面"}},
        },
    },
}


DESKTOP_TOOLS: dict[str, dict] = {
    "list_windows": {"def": LIST_WINDOWS_DEF, "fn": list_windows},
    "switch_window": {"def": SWITCH_WINDOW_DEF, "fn": switch_window},
    "window_action": {"def": WINDOW_ACTION_DEF, "fn": window_action},
    "run_hotkey": {"def": RUN_HOTKEY_DEF, "fn": run_hotkey},
    "taskbar_click": {"def": TASKBAR_CLICK_DEF, "fn": taskbar_click},
    "get_foreground_window": {"def": GET_FOREGROUND_DEF, "fn": get_foreground_window},
    "focus_input": {"def": FOCUS_INPUT_DEF, "fn": focus_input},
    "scroll": {"def": SCROLL_DEF, "fn": scroll},
    "open_app": {"def": OPEN_APP_DEF, "fn": open_app},
    "list_files": {"def": LIST_FILES_DEF, "fn": list_files},
}


def desktop_tool_defs() -> list[dict]:
    return [t["def"] for t in DESKTOP_TOOLS.values()]


def call_desktop_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in DESKTOP_TOOLS:
        return f"[error] unknown desktop tool: {name}"
    fn = DESKTOP_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"