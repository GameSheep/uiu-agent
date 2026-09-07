"""Windows Input Method Editor (IME) Controller & Pinyin Interference Suppressor.

Prevents Chinese IMEs (Sogou, Microsoft Pinyin) from intercepting automated keystrokes,
eating backspaces, or popping up candidate boxes during desktop automation.
"""

from __future__ import annotations

import ctypes
import sys
import time
from contextlib import contextmanager
from typing import Iterator


# IME conversion constants
# 0 = IME_CMODE_ALPHANUMERIC (Pure English alphanumeric mode)
IME_CMODE_ALPHANUMERIC = 0x0000
IME_CMODE_NATIVE = 0x0001
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_SETCONVERSIONMODE = 0x0002


def set_ime_to_english(hwnd: int | None = None) -> bool:
    """Force the target window (or active foreground window) into English direct input mode.
    Disables Chinese Pinyin candidate popups.
    """
    if sys.platform != "win32":
        return False

    user32 = ctypes.windll.user32
    target_hwnd = hwnd or user32.GetForegroundWindow()
    if not target_hwnd:
        return False

    try:
        imm32 = ctypes.windll.imm32
        himc = imm32.ImmGetContext(int(target_hwnd))
        if himc:
            try:
                # Set conversion status to pure alphanumeric
                imm32.ImmSetConversionStatus(himc, IME_CMODE_ALPHANUMERIC, 0)
                # Also notify via WM_IME_CONTROL message
                user32.SendMessageW(int(target_hwnd), WM_IME_CONTROL, IMC_SETCONVERSIONMODE, IME_CMODE_ALPHANUMERIC)
                return True
            finally:
                imm32.ImmReleaseContext(int(target_hwnd), himc)
        else:
            # Try default IME window if window has no private context
            h_def_ime = imm32.ImmGetDefaultIMEWnd(int(target_hwnd))
            if h_def_ime:
                user32.SendMessageW(h_def_ime, WM_IME_CONTROL, IMC_SETCONVERSIONMODE, IME_CMODE_ALPHANUMERIC)
                return True
    except Exception:
        pass

    return False


def get_ime_conversion_status(hwnd: int | None = None) -> tuple[int, int] | None:
    """Get the current conversion mode and sentence mode of the window's IME context."""
    if sys.platform != "win32":
        return None

    user32 = ctypes.windll.user32
    target_hwnd = hwnd or user32.GetForegroundWindow()
    if not target_hwnd:
        return None

    try:
        imm32 = ctypes.windll.imm32
        himc = imm32.ImmGetContext(int(target_hwnd))
        if himc:
            try:
                conv = ctypes.c_ulong()
                sent = ctypes.c_ulong()
                if imm32.ImmGetConversionStatus(himc, ctypes.byref(conv), ctypes.byref(sent)):
                    return int(conv.value), int(sent.value)
            finally:
                imm32.ImmReleaseContext(int(target_hwnd), himc)
    except Exception:
        pass

    return None


@contextmanager
def preserve_ime_mode(hwnd: int | None = None) -> Iterator[None]:
    """Context manager that forces English mode for keystrokes, then restores original IME mode."""
    if sys.platform != "win32":
        yield
        return

    user32 = ctypes.windll.user32
    target_hwnd = hwnd or user32.GetForegroundWindow()

    orig_status = get_ime_conversion_status(target_hwnd)
    set_ime_to_english(target_hwnd)

    try:
        yield
    finally:
        if orig_status is not None and target_hwnd:
            try:
                imm32 = ctypes.windll.imm32
                himc = imm32.ImmGetContext(int(target_hwnd))
                if himc:
                    try:
                        imm32.ImmSetConversionStatus(himc, orig_status[0], orig_status[1])
                    finally:
                        imm32.ImmReleaseContext(int(target_hwnd), himc)
            except Exception:
                pass
