"""Multi-DPI Scaler & High-Precision Coordinate Anti-Drift Engine.

Solves coordinate mismatch across:
1. Multi-monitor setups with mixed DPI scaling (100%, 125%, 150%, 200%).
2. Physical pixels (OCR / OpenCV / screenshots) vs Logical DIPs (Win32 SendInput / PyAutoGUI).
3. Resolution-independent normalized coordinates ([0.0, 1.0]) for cross-device workflows.
4. Optical safe-zone targeting (golden-ratio centering, input-box auto-alignment, anti-bevel drift).
"""

from __future__ import annotations

import ctypes
import math
import sys
from typing import Any


def get_dpi_for_system() -> int:
    """Get system base DPI (standard default is 96, meaning 100% scale)."""
    if sys.platform != "win32":
        return 96
    try:
        user32 = ctypes.windll.user32
        if hasattr(user32, "GetDpiForSystem"):
            dpi = user32.GetDpiForSystem()
            if dpi > 0:
                return int(dpi)
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        if hdc:
            # LOGPIXELSX = 88
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
            ctypes.windll.user32.ReleaseDC(0, hdc)
            if dpi > 0:
                return int(dpi)
    except Exception:
        pass
    return 96


def get_dpi_scale(hwnd: int | None = None, point: tuple[int, int] | None = None) -> float:
    """Get the DPI scaling factor (e.g., 1.0, 1.25, 1.5, 2.0).

    Args:
        hwnd: Optional window handle.
        point: Optional (x, y) coordinate on screen.
    """
    if sys.platform != "win32":
        return 1.0

    # 1. Window-specific DPI (Windows 10 1607+)
    if hwnd and hwnd > 0:
        try:
            user32 = ctypes.windll.user32
            if hasattr(user32, "GetDpiForWindow"):
                dpi = user32.GetDpiForWindow(int(hwnd))
                if dpi > 0:
                    return float(dpi) / 96.0
        except Exception:
            pass

    # 2. Monitor-specific DPI via point
    if point is not None:
        try:
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            shcore = ctypes.windll.shcore
            pt = ctypes.wintypes.POINT(int(point[0]), int(point[1]))
            # MONITOR_DEFAULTTONEAREST = 2
            hmon = user32.MonitorFromPoint(pt, 2)
            if hmon:
                dpi_x = ctypes.c_uint()
                dpi_y = ctypes.c_uint()
                # MDT_EFFECTIVE_DPI = 0
                hr = shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
                if hr == 0 and dpi_x.value > 0:
                    return float(dpi_x.value) / 96.0
        except Exception:
            pass

    # 3. System DPI fallback
    sys_dpi = get_dpi_for_system()
    return float(sys_dpi) / 96.0


def list_monitors_geometry() -> list[dict[str, Any]]:
    """List all connected monitors with their bounds, scaling, and primary status."""
    if sys.platform != "win32":
        return [{
            "device": "DISPLAY0",
            "rect": (0, 0, 1920, 1080),
            "scale": 1.0,
            "is_primary": True,
        }]

    monitors = []
    try:
        import win32api
        for m in win32api.EnumDisplayMonitors():
            info = win32api.GetMonitorInfo(m[0])
            rect = info.get("Monitor", (0, 0, 1920, 1080))
            is_primary = bool(info.get("Flags", 0) & 1)
            scale = get_dpi_scale(point=(rect[0] + 10, rect[1] + 10))
            monitors.append({
                "device": info.get("Device", ""),
                "rect": rect,  # (left, top, right, bottom)
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
                "scale": scale,
                "is_primary": is_primary,
            })
    except Exception:
        # Fallback to system metrics
        scale = get_dpi_scale()
        monitors.append({
            "device": "DEFAULT",
            "rect": (0, 0, 1920, 1080),
            "width": 1920,
            "height": 1080,
            "scale": scale,
            "is_primary": True,
        })
    return monitors


def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Get the bounding rectangle of the virtual multi-monitor desktop.
    Returns: (left, top, width, height)
    """
    if sys.platform != "win32":
        return 0, 0, 1920, 1080
    try:
        user32 = ctypes.windll.user32
        # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77
        # SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
        x = user32.GetSystemMetrics(76)
        y = user32.GetSystemMetrics(77)
        w = user32.GetSystemMetrics(78)
        h = user32.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return int(x), int(y), int(w), int(h)
    except Exception:
        pass
    return 0, 0, 1920, 1080


def physical_to_logical(
    x: int | float,
    y: int | float,
    hwnd: int | None = None,
    custom_scale: float | None = None,
) -> tuple[int, int]:
    """Convert physical image buffer pixels (OCR/OpenCV) to logical desktop coordinates."""
    scale = custom_scale if custom_scale is not None else get_dpi_scale(hwnd=hwnd, point=(int(x), int(y)))
    if scale <= 0.0:
        scale = 1.0
    return int(round(x / scale)), int(round(y / scale))


def logical_to_physical(
    x: int | float,
    y: int | float,
    hwnd: int | None = None,
    custom_scale: float | None = None,
) -> tuple[int, int]:
    """Convert logical desktop coordinates to physical pixels."""
    scale = custom_scale if custom_scale is not None else get_dpi_scale(hwnd=hwnd, point=(int(x), int(y)))
    if scale <= 0.0:
        scale = 1.0
    return int(round(x * scale)), int(round(y * scale))


def normalize_coordinates(
    x: int | float,
    y: int | float,
    bounds: tuple[int, int, int, int] | None = None,
) -> tuple[float, float]:
    """Normalize absolute coordinates to [0.0, 1.0] relative to screen/region bounds.

    bounds format: (left, top, width, height)
    """
    if bounds is None:
        bounds = get_virtual_screen_bounds()

    bx, by, bw, bh = bounds
    if bw <= 0:
        bw = 1
    if bh <= 0:
        bh = 1

    norm_x = (x - bx) / float(bw)
    norm_y = (y - by) / float(bh)
    return round(float(norm_x), 4), round(float(norm_y), 4)


def denormalize_coordinates(
    norm_x: float,
    norm_y: float,
    bounds: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    """Convert normalized [0.0, 1.0] coordinates back to absolute integer coordinates."""
    if bounds is None:
        bounds = get_virtual_screen_bounds()

    bx, by, bw, bh = bounds
    abs_x = bx + int(round(norm_x * bw))
    abs_y = by + int(round(norm_y * bh))
    return abs_x, abs_y


def calculate_safe_target(
    box: tuple[int, int, int, int] | dict[str, Any],
    strategy: str = "center",
    margin_ratio: float = 0.15,
) -> tuple[int, int]:
    """Compute anti-drift click coordinates inside a bounding box.

    Avoids borders, scrollbars, close crosses, or bevel drop-shadows.

    Strategies:
    - 'center': Mathematical center (x + w/2, y + h/2).
    - 'safe_center': Center within safe inner margins (default 15% padding).
    - 'input_field': Left-aligned safe area (25% from left edge, 50% height),
                     ideal for clicking text inputs without hitting trailing clear icons.
    - 'right_action': Right-aligned area (85% from left edge, 50% height),
                      ideal for dropdown chevrons or expand arrows.

    Box formats accepted:
    - (x, y, w, h)
    - dict with 'x', 'y', 'w', 'h'
    - dict with 'x1', 'y1', 'x2', 'y2'
    """
    if isinstance(box, dict):
        if "w" in box and "h" in box:
            x = int(box.get("x", 0))
            y = int(box.get("y", 0))
            w = int(box.get("w", 0))
            h = int(box.get("h", 0))
        elif "x1" in box and "x2" in box:
            x1 = int(box["x1"])
            y1 = int(box["y1"])
            x2 = int(box["x2"])
            y2 = int(box["y2"])
            x, y, w, h = x1, y1, x2 - x1, y2 - y1
        else:
            x = int(box.get("cx", 0))
            y = int(box.get("cy", 0))
            return x, y
    else:
        x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])

    if w <= 0 or h <= 0:
        return x, y

    margin_x = int(w * margin_ratio)
    margin_y = int(h * margin_ratio)

    if strategy == "input_field":
        # Click at ~25% from left, vertically centered
        target_x = x + max(margin_x, int(w * 0.25))
        target_y = y + h // 2
    elif strategy == "right_action":
        # Click at ~85% from left, vertically centered
        target_x = x + min(w - margin_x, int(w * 0.85))
        target_y = y + h // 2
    elif strategy == "safe_center":
        # Inner center clamped to safe margins
        safe_w = max(1, w - 2 * margin_x)
        safe_h = max(1, h - 2 * margin_y)
        target_x = x + margin_x + safe_w // 2
        target_y = y + margin_y + safe_h // 2
    else:
        # Default midpoint
        target_x = x + w // 2
        target_y = y + h // 2

    return target_x, target_y


def calibrate_screen_alignment() -> dict[str, Any]:
    """Run diagnostics verifying coordinate alignment across display, DPI, and screenshot buffers."""
    monitors = list_monitors_geometry()
    virt_bounds = get_virtual_screen_bounds()
    sys_scale = get_dpi_scale()

    import pyautogui
    screen_w, screen_h = pyautogui.size()

    is_aligned = (screen_w == virt_bounds[2] and screen_h == virt_bounds[3])

    return {
        "status": "calibrated",
        "system_scale": sys_scale,
        "pyautogui_size": (screen_w, screen_h),
        "virtual_bounds": virt_bounds,
        "is_aligned": is_aligned,
        "monitors_count": len(monitors),
        "monitors": monitors,
    }
