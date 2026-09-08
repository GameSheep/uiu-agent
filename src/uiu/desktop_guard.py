"""Desktop Guard — Execution Context & Keyboard/Mouse Non-Interference Safety.

Core invariants:
1. When uiu is in background/idle state with no dialogue, it MUST NEVER interfere with
   the keyboard or mouse.
2. Controlled desktop operations (clicking, typing, pressing hotkeys, window focus stealing)
   are ONLY permitted when:
   - User explicitly converses in uiu to execute a command (USER_DIALOGUE)
   - A scheduled cron job is actively triggered at its due time (CRON_SCHEDULED_RUN)
3. During CRON_SCHEDULED_RUN, if the user is actively using the mouse or keyboard
   (detected via Windows GetLastInputInfo), actions yield/block to avoid messing up the
   user's live typing or mouse clicks.
"""

from __future__ import annotations

import contextlib
import enum
import sys
import threading
import time
from typing import Any, Generator


class ExecutionContext(str, enum.Enum):
    """The execution state of the agent system."""
    IDLE = "IDLE"                                   # Default background state: NO keyboard/mouse allowed
    USER_DIALOGUE = "USER_DIALOGUE"                 # Explicit conversation turn from user
    CRON_SCHEDULED_RUN = "CRON_SCHEDULED_RUN"       # Scheduled cron job triggered at due time


# Thread-local storage for per-thread execution context
_local = threading.local()

# Physical keyboard, mouse, and window focus tools that could disrupt the user
CONTROLLED_DESKTOP_TOOLS = frozenset({
    # Mouse interactions
    "mouse_click_at",
    "mouse_move_to",
    "mouse_drag",
    "mouse_scroll_at",
    "click_text",
    "resilient_click",
    "mouse_click",
    # Keyboard interactions
    "type_text",
    "keyboard_shortcut",
    "press_key",
    "text_paste",
    "paste_text",
    # Window focus / foreground stealing
    "window_focus",
    "app_open_or_focus",
    # Composite automated routines
    "send_wechat",
    "macro_play",
    "askui_autopilot",
    "screen_react",
    "fast_pipeline",
    "gui_action_pipeline",
    # Keyboard layout / IME modification
    "ensure_english_ime",
})


def get_current_context() -> ExecutionContext:
    """Retrieve the current thread's execution context (defaults to IDLE)."""
    return getattr(_local, "context", ExecutionContext.IDLE)


def get_current_source() -> str:
    """Retrieve metadata about the caller (e.g. 'user:tui', 'cron:daily_report')."""
    return getattr(_local, "source", "system")


@contextlib.contextmanager
def execution_guard(context: ExecutionContext, source: str = "") -> Generator[None, None, None]:
    """Scoped execution guard that elevates the context from IDLE to USER_DIALOGUE or CRON_SCHEDULED_RUN."""
    prev_context = getattr(_local, "context", ExecutionContext.IDLE)
    prev_source = getattr(_local, "source", "")
    _local.context = context
    _local.source = source
    try:
        yield
    finally:
        _local.context = prev_context
        _local.source = prev_source


def get_user_idle_seconds() -> float:
    """Calculate the number of seconds elapsed since the user last physically used keyboard or mouse.
    
    Uses Windows GetLastInputInfo API. Returns high number on non-Windows platforms.
    """
    if sys.platform != "win32":
        return 9999.0

    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0.0, float(millis) / 1000.0)
    except Exception:
        pass

    return 9999.0


def check_desktop_action_allowed(tool_name: str, min_user_idle_s: float = 3.0) -> tuple[bool, str]:
    """Check if a tool is permitted to interact with desktop/keyboard/mouse right now."""
    if tool_name not in CONTROLLED_DESKTOP_TOOLS:
        return True, "非受控操作（无键鼠干扰）"

    ctx = get_current_context()
    source = get_current_source()

    if ctx == ExecutionContext.IDLE:
        return False, (
            f"[blocked] 静默后台免干扰拦截：当前处于后台静默状态（未收到明确用户对话指令且非定时任务到点），"
            f"严禁执行 '{tool_name}' 干扰系统键盘与鼠标。"
        )

    if ctx == ExecutionContext.USER_DIALOGUE:
        return True, f"放行：用户明确在对话中发起指令 ({source})"

    if ctx == ExecutionContext.CRON_SCHEDULED_RUN:
        # Avoid disrupting human user if they are currently typing or using the mouse
        idle_sec = get_user_idle_seconds()
        if idle_sec < min_user_idle_s:
            return False, (
                f"[blocked] 定时任务避让保护：检测到用户正在使用键盘或鼠标（最近活跃于 {idle_sec:.1f} 秒前），"
                f"为保护用户工作不被打扰，已暂停执行 '{tool_name}'。"
            )
        return True, f"放行：定时任务到点执行且用户处于空闲状态 ({source})"

    return False, f"[blocked] 未知执行上下文: {ctx}"


def assert_desktop_allowed(tool_name: str) -> None:
    """Raise PermissionError if the tool is not allowed in the current context."""
    allowed, reason = check_desktop_action_allowed(tool_name)
    if not allowed:
        raise PermissionError(reason)
