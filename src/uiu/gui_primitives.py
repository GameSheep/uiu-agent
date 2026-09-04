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
    pyautogui.PAUSE = 0.05
    return pyautogui


def mouse_click(
    x: int,
    y: int,
    button: Literal["left", "right", "middle"] = "left",
    clicks: int = 1,
    interval: float = 0.1,
    duration: float = 0.15
) -> str:
    ag = _get_pyautogui()
    try:
        ag.moveTo(x, y, duration=duration)
        ag.click(x=x, y=y, clicks=clicks, interval=interval, button=button)
        return f"[ok] 已在 ({x}, {y}) 执行 {button} 键点击 {clicks} 次"
    except Exception as e:
        return f"[error] 鼠标点击失败: {type(e).__name__}: {e}"


def mouse_drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
    button: str = "left"
) -> str:
    ag = _get_pyautogui()
    try:
        ag.moveTo(start_x, start_y, duration=0.15)
        ag.dragTo(end_x, end_y, duration=duration, button=button)
        return f"[ok] 已拖拽从 ({start_x}, {start_y}) 到 ({end_x}, {end_y})"
    except Exception as e:
        return f"[error] 鼠标拖拽失败: {type(e).__name__}: {e}"


def mouse_scroll(clicks: int, x: int | None = None, y: int | None = None) -> str:
    ag = _get_pyautogui()
    try:
        if x is not None and y is not None:
            ag.moveTo(x, y, duration=0.1)
        ag.scroll(clicks)
        time.sleep(0.2)
        direction = "向上" if clicks > 0 else "向下"
        return f"[ok] 已{direction}滚动 {abs(clicks)} 单位"
    except Exception as e:
        return f"[error] 鼠标滚轮失败: {type(e).__name__}: {e}"


def press_hotkey(keys: list[str]) -> str:
    ag = _get_pyautogui()
    try:
        clean_keys = [k.lower().strip() for k in keys]
        ag.hotkey(*clean_keys)
        time.sleep(0.15)
        return f"[ok] 已触发快捷键: {' + '.join(clean_keys)}"
    except Exception as e:
        return f"[error] 按键组合失败: {type(e).__name__}: {e}"


def press_key(key_name: str, presses: int = 1, interval: float = 0.1) -> str:
    ag = _get_pyautogui()
    try:
        ag.press(key_name.lower().strip(), presses=presses, interval=interval)
        return f"[ok] 已按键 '{key_name}' {presses} 次"
    except Exception as e:
        return f"[error] 单键输入失败: {type(e).__name__}: {e}"


def paste_text(text: str, clear_before: bool = False) -> str:
    ag = _get_pyautogui()
    try:
        import win32clipboard
        import win32con

        if clear_before:
            ag.hotkey("ctrl", "a")
            time.sleep(0.05)
            ag.press("backspace")
            time.sleep(0.05)

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
        time.sleep(0.05)

        ag.hotkey("ctrl", "v")
        time.sleep(0.15)
        return f"[ok] 已成功粘贴文本（长度: {len(text)}）"
    except Exception as e:
        return f"[error] 剪贴板粘贴失败: {type(e).__name__}: {e}"