"""Smart Window Layout & Snapping Automation Engine.

Enables:
1. Automated dual-app side-by-side tiling (`tile_windows(app1, app2)`).
2. Screen work-area aware snapping (`snap_window(keyword, position)`).
3. Non-destructive layout saving and restoration (`save_window_layout()`, `restore_window_layout()`).
4. Simultaneous multi-window vision visibility for complex cross-software agents.
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Any, Literal


def get_work_area() -> tuple[int, int, int, int]:
    """Get the desktop work area bounds (excluding Windows taskbar).
    Returns: (left, top, width, height)
    """
    if sys.platform != "win32":
        return 0, 0, 1920, 1080

    try:
        import ctypes.wintypes
        rect = ctypes.wintypes.RECT()
        # SPI_GETWORKAREA = 0x0030
        res = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        if res:
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            return int(rect.left), int(rect.top), int(w), int(h)
    except Exception:
        pass

    return 0, 0, 1920, 1080


def _resolve_hwnd(target: int | str) -> int | None:
    """Resolve a window handle from either an integer hwnd or a window title keyword."""
    if isinstance(target, int) and target > 0:
        return target

    from .window_manager import find_window
    win = find_window(str(target))
    return int(win["hwnd"]) if win else None


def snap_window(
    target: int | str,
    position: Literal["left", "right", "top", "bottom", "maximize", "center"] = "left",
) -> str:
    """Snap a target window to a specified sector of the screen work area."""
    if sys.platform != "win32":
        return "[error] 窗口布局仅支持 Windows 平台"

    hwnd = _resolve_hwnd(target)
    if not hwnd:
        return f"[error] 未找到目标窗口: {target}"

    import win32con
    import win32gui

    # Restore window if minimized
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.05)

    wx, wy, ww, wh = get_work_area()

    if position == "maximize":
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return f"[ok] 窗口 {hwnd} 已最大化"

    half_w = ww // 2
    half_h = wh // 2

    if position == "left":
        nx, ny, nw, nh = wx, wy, half_w, wh
    elif position == "right":
        nx, ny, nw, nh = wx + half_w, wy, half_w, wh
    elif position == "top":
        nx, ny, nw, nh = wx, wy, ww, half_h
    elif position == "bottom":
        nx, ny, nw, nh = wx, wy + half_h, ww, half_h
    elif position == "center":
        cw = int(ww * 0.75)
        ch = int(wh * 0.75)
        nx = wx + (ww - cw) // 2
        ny = wy + (wh - ch) // 2
        nw, nh = cw, ch
    else:
        return f"[error] 未知吸附方位: {position}"

    win32gui.MoveWindow(hwnd, nx, ny, nw, nh, True)
    win32gui.SetForegroundWindow(hwnd)
    return f"[ok] 窗口已吸附至 {position} 区域: ({nx}, {ny}, {nw}, {nh})"


def tile_windows(
    app1: str,
    app2: str,
    direction: Literal["horizontal", "vertical"] = "horizontal",
) -> dict[str, Any]:
    """Tile two applications side-by-side or top-and-bottom for dual-app visual automation."""
    from .window_manager import open_or_focus_app, find_window

    open_or_focus_app(app1)
    time.sleep(0.1)
    open_or_focus_app(app2)
    time.sleep(0.1)

    hwnd1 = _resolve_hwnd(app1)
    hwnd2 = _resolve_hwnd(app2)

    if not hwnd1 or not hwnd2:
        return {
            "success": False,
            "error": f"未能找到应用窗口 (hwnd1={hwnd1}, hwnd2={hwnd2})",
        }

    if direction == "horizontal":
        res1 = snap_window(hwnd1, "left")
        res2 = snap_window(hwnd2, "right")
    else:
        res1 = snap_window(hwnd1, "top")
        res2 = snap_window(hwnd2, "bottom")

    return {
        "success": True,
        "direction": direction,
        "app1": {"name": app1, "hwnd": hwnd1, "status": res1},
        "app2": {"name": app2, "hwnd": hwnd2, "status": res2},
    }


def save_window_layout(targets: list[int | str]) -> list[dict[str, Any]]:
    """Save the current position, size, and state of windows to allow later restoration."""
    if sys.platform != "win32":
        return []

    import win32gui
    records = []
    for t in targets:
        hwnd = _resolve_hwnd(t)
        if hwnd and win32gui.IsWindow(hwnd):
            rect = win32gui.GetWindowRect(hwnd)
            records.append({
                "hwnd": hwnd,
                "target": t,
                "rect": rect,  # (left, top, right, bottom)
            })
    return records


def restore_window_layout(records: list[dict[str, Any]]) -> str:
    """Restore windows back to their saved positions."""
    if sys.platform != "win32":
        return "[ok]"

    import win32gui
    restored = 0
    for rec in records:
        hwnd = rec.get("hwnd")
        rect = rec.get("rect")
        if hwnd and rect and win32gui.IsWindow(hwnd):
            l, t, r, b = rect
            win32gui.MoveWindow(hwnd, l, t, r - l, b - t, True)
            restored += 1
    return f"[ok] 已恢复 {restored} 个窗口的原始布局"
