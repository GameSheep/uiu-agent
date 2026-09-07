"""Global Safety Hotkey Emergency Brake & Visual Spotlight HUD.

Inspired by Anthropic Computer Use, OSWorld, and industrial human-in-the-loop safety protocols.
1. Global Emergency Stop: Monitors low-level key state (Ctrl+Alt+Shift+Q or Pause/Break) to instantly abort agent control.
2. Visual Spotlight HUD: Highlights target click coordinates on screen for transparency and human reassurance.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any, Callable


# Global emergency stop flag
_EMERGENCY_STOP_EVENT = threading.Event()
_LISTENER_THREAD: threading.Thread | None = None
_LISTENER_RUNNING = False


# Win32 Virtual Key Codes
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12       # Alt key
VK_PAUSE = 0x13      # Pause/Break key
VK_Q = 0x51          # Q key
VK_ESCAPE = 0x1B     # Escape


def is_emergency_stop_triggered() -> bool:
    """Check if the human operator has pressed the panic hotkey."""
    return _EMERGENCY_STOP_EVENT.is_set()


def reset_emergency_stop() -> None:
    """Clear emergency stop flag to allow new tasks to proceed."""
    _EMERGENCY_STOP_EVENT.clear()


def trigger_emergency_stop(reason: str = "User panic key triggered") -> None:
    """Manually or programmatically trigger emergency stop."""
    _EMERGENCY_STOP_EVENT.set()


def _is_key_pressed(vk_code: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk_code) & 0x8000)
    except Exception:
        return False


def _panic_listener_loop():
    global _LISTENER_RUNNING
    while _LISTENER_RUNNING:
        # Check combination: Ctrl + Alt + Shift + Q
        ctrl = _is_key_pressed(VK_CONTROL)
        alt = _is_key_pressed(VK_MENU)
        shift = _is_key_pressed(VK_SHIFT)
        q = _is_key_pressed(VK_Q)

        # Or dedicated Pause/Break key
        pause = _is_key_pressed(VK_PAUSE)

        if (ctrl and alt and shift and q) or pause:
            trigger_emergency_stop("Global Panic Hotkey (Ctrl+Alt+Shift+Q / Pause) detected!")
            break

        time.sleep(0.04)


def start_emergency_listener() -> None:
    """Start the background daemon thread listening for global emergency stop hotkeys."""
    global _LISTENER_THREAD, _LISTENER_RUNNING
    if sys.platform != "win32":
        return

    if _LISTENER_RUNNING and _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
        return

    _LISTENER_RUNNING = True
    reset_emergency_stop()
    _LISTENER_THREAD = threading.Thread(target=_panic_listener_loop, daemon=True)
    _LISTENER_THREAD.start()


def stop_emergency_listener() -> None:
    """Stop the background emergency hotkey listener."""
    global _LISTENER_RUNNING
    _LISTENER_RUNNING = False


def flash_spotlight_indicator(x: int, y: int, radius: int = 25, duration: float = 0.15) -> None:
    """Draw a temporary visual spotlight beacon at the click target on Windows screen.
    Uses Win32 GDI inverted ellipse for zero latency and zero dependency overlay.
    """
    if sys.platform != "win32":
        return

    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        hdc = user32.GetDC(0)
        if not hdc:
            return

        try:
            # Draw inverted target crosshair / circle
            # PATINVERT = 0x005A0049
            # Draw horizontal crosshair
            gdi32.PatBlt(hdc, x - radius, y - 1, radius * 2, 3, 0x005A0049)
            # Draw vertical crosshair
            gdi32.PatBlt(hdc, x - 1, y - radius, 3, radius * 2, 0x005A0049)

            time.sleep(duration)

            # Invert back to restore screen pixels
            gdi32.PatBlt(hdc, x - radius, y - 1, radius * 2, 3, 0x005A0049)
            gdi32.PatBlt(hdc, x - 1, y - radius, 3, radius * 2, 0x005A0049)
        finally:
            user32.ReleaseDC(0, hdc)
    except Exception:
        pass
