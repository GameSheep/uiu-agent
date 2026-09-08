"""Universal GUI Primitives — Basic Mouse & Keyboard Actions."""

from __future__ import annotations

import ctypes
import time
from typing import Literal

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _get_pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.01
    return pyautogui


def mouse_click(
    x: int | float,
    y: int | float,
    button: Literal["left", "right", "middle"] = "left",
    clicks: int = 1,
    interval: float = 0.02,
    duration: float = 0.0,
    is_physical: bool = False,
) -> str:
    from .dpi_manager import denormalize_coordinates, physical_to_logical
    if isinstance(x, float) and 0.0 <= x <= 1.0 and isinstance(y, float) and 0.0 <= y <= 1.0:
        x, y = denormalize_coordinates(x, y)
    elif is_physical:
        x, y = physical_to_logical(x, y)
    else:
        x, y = int(round(x)), int(round(y))

    ag = _get_pyautogui()
    try:
        ag.moveTo(x, y, duration=duration)
        ag.click(x=x, y=y, clicks=clicks, interval=interval, button=button)
        return f"[ok] 已在 ({x}, {y}) 执行 {button} 键点击 {clicks} 次"
    except Exception as e:
        return f"[error] 鼠标点击失败: {type(e).__name__}: {e}"


def mouse_move(x: int | float, y: int | float, duration: float = 0.0, is_physical: bool = False) -> str:
    from .dpi_manager import denormalize_coordinates, physical_to_logical
    if isinstance(x, float) and 0.0 <= x <= 1.0 and isinstance(y, float) and 0.0 <= y <= 1.0:
        x, y = denormalize_coordinates(x, y)
    elif is_physical:
        x, y = physical_to_logical(x, y)
    else:
        x, y = int(round(x)), int(round(y))

    ag = _get_pyautogui()
    try:
        ag.moveTo(x, y, duration=duration)
        return f"[ok] 鼠标已移动至 ({x}, {y})"
    except Exception as e:
        return f"[error] 鼠标移动失败: {type(e).__name__}: {e}"



def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.2,
    button: str = "left"
) -> str:
    ag = _get_pyautogui()
    try:
        ag.moveTo(start_x, start_y, duration=0.0)
        ag.dragTo(end_x, end_y, duration=duration, button=button)
        return f"[ok] 已拖拽从 ({start_x}, {start_y}) 到 ({end_x}, {end_y})"
    except Exception as e:
        return f"[error] 鼠标拖拽失败: {type(e).__name__}: {e}"


def mouse_scroll(clicks: int, x: int | None = None, y: int | None = None) -> str:
    ag = _get_pyautogui()
    try:
        if x is not None and y is not None:
            ag.moveTo(x, y, duration=0.0)
        ag.scroll(clicks)
        time.sleep(0.05)
        direction = "向上" if clicks > 0 else "向下"
        return f"[ok] 已{direction}滚动 {abs(clicks)} 单位"
    except Exception as e:
        return f"[error] 鼠标滚轮失败: {type(e).__name__}: {e}"


def _valid_key_names() -> set[str]:
    """Return the set of key names pyautogui can press (lowercase)."""
    try:
        ag = _get_pyautogui()
        return {k.lower() for k in getattr(ag, "KEYBOARD_KEYS", [])}
    except Exception:
        # pyautogui unavailable: fall back to a conservative allowlist
        base = {
            "enter", "esc", "escape", "tab", "space", "backspace", "delete",
            "ctrl", "control", "alt", "shift", "win", "cmd", "up", "down",
            "left", "right", "home", "end", "pageup", "pagedown",
            "a", "c", "v", "x", "z", "y", "f1", "f2", "f3", "f4", "f5",
        }
        return base


def press_hotkey(keys: list[str]) -> str:
    if not keys:
        return "[error] 按键列表为空"
    if len(keys) > 4:
        return "[error] 组合键最多 4 个"
    clean_keys = [str(k).lower().strip() for k in keys]
    if any(not k for k in clean_keys):
        return "[error] 按键名不能为空"
    valid = _valid_key_names()
    bad = [k for k in clean_keys if k not in valid]
    if bad:
        return f"[error] 非法按键名: {', '.join(bad)}"
    ag = _get_pyautogui()
    try:
        ag.hotkey(*clean_keys)
        time.sleep(0.05)
        return f"[ok] 已触发快捷键: {' + '.join(clean_keys)}"
    except Exception as e:
        return f"[error] 按键组合失败: {type(e).__name__}: {e}"


def press_key(key_name: str, presses: int = 1, interval: float = 0.05) -> str:
    name = (key_name or "").lower().strip()
    if not name:
        return "[error] 按键名不能为空"
    valid = _valid_key_names()
    if name not in valid:
        return f"[error] 非法按键名: {name}"
    ag = _get_pyautogui()
    try:
        ag.press(name, presses=presses, interval=interval)
        return f"[ok] 已按键 '{key_name}' {presses} 次"
    except Exception as e:
        return f"[error] 单键输入失败: {type(e).__name__}: {e}"


def paste_text(text: str, clear_before: bool = False) -> str:
    text = text or ""
    if len(text) > 100 * 1024:
        return "[error] 粘贴文本过长（上限 100KB）"
    ag = _get_pyautogui()
    try:
        import win32clipboard
        import win32con

        if clear_before:
            ag.hotkey("ctrl", "a")
            time.sleep(0.02)
            ag.press("backspace")
            time.sleep(0.02)

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        time.sleep(0.02)

        ag.hotkey("ctrl", "v")
        time.sleep(0.05)

        return f"[ok] 已成功粘贴文本（长度: {len(text)}）"
    except Exception as e:
        return f"[error] 剪贴板粘贴失败: {type(e).__name__}: {e}"