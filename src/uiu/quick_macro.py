"""Quick Macro (按键精灵模式) — Instant F10 Record / F12 Replay / F11 Abort loop.

Classic zero-thinking macro loop:
- Move mouse to start position
- Press F10 -> starts recording (1 high beep)
- Perform actions -> click, keys, scrolls
- Press F10 again -> stops recording & saves _quick_loop.json (2 double beeps)
- Press F12 -> instant sub-second replay 1 time (1 low confirmation beep)
- Press Ctrl+F12 -> replay loop (default 10 times)
- Press F11 at any time -> instant emergency abort (long low beep)
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

from .macro_player import play_steps
from .macro_recorder import (
    HOOKPROC,
    _CONTROL_KEYS,
    _KBDLLHOOKSTRUCT,
    _MOUSE_BUTTON,
    _MSLLHOOKSTRUCT,
    _mouse_wheel_clicks,
    _synthesize,
    _user32,
    load_macro,
    macros_dir,
    save_macro,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    WM_KEYDOWN,
    WM_LBUTTONDOWN,
    WM_MBUTTONDOWN,
    WM_MOUSEWHEEL,
    WM_RBUTTONDOWN,
    WM_SYSKEYDOWN,
)

# Virtual-Key codes
VK_F10 = 0x79
VK_F11 = 0x7A
VK_F12 = 0x7B
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

QUICK_MACRO_NAME = "_quick_loop"


def play_sound(sound_type: str) -> None:
    """Play distinctive non-blocking audio feedback via Windows Beep."""
    if os.name != "nt":
        return

    def _beep():
        try:
            k32 = ctypes.windll.kernel32
            if sound_type == "start_record":
                # High single chirp (1000Hz, 150ms)
                k32.Beep(1000, 150)
            elif sound_type == "stop_record":
                # High double chirp (1400Hz 100ms, 1800Hz 150ms)
                k32.Beep(1400, 100)
                time.sleep(0.04)
                k32.Beep(1800, 150)
            elif sound_type == "play_start":
                # Low solid start beep (800Hz, 80ms)
                k32.Beep(800, 80)
            elif sound_type == "play_finish":
                # Bright finish beep (1200Hz, 100ms)
                k32.Beep(1200, 100)
            elif sound_type == "abort":
                # Deep low warning tone (400Hz, 280ms)
                k32.Beep(400, 280)
        except Exception:
            pass

    threading.Thread(target=_beep, daemon=True).start()


def is_ctrl_pressed() -> bool:
    """Check if Ctrl modifier key is currently held down."""
    try:
        return bool(
            (_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            or (_user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000)
            or (_user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000)
        )
    except Exception:
        return False


def _get_macro_path(workspace_root: Path | None = None) -> Path:
    if workspace_root is None:
        from .macros import _workspace_root
        workspace_root = _workspace_root() or (Path.cwd() / "workspace")
    d = macros_dir(workspace_root)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{QUICK_MACRO_NAME}.json"


class QuickMacroDaemon:
    """Global hotkey daemon running the F10/F12/F11 QuickMacro state machine."""

    def __init__(self, workspace_root: Path | None = None,
                 on_status_change: Callable[[str, str], None] | None = None):
        self.workspace_root = workspace_root
        self.macro_file = _get_macro_path(workspace_root)
        self.on_status_change = on_status_change

        # State: IDLE, RECORDING, READY, PLAYING
        self.state = "IDLE"
        self._stop_daemon = threading.Event()
        self._play_stop_flag = threading.Event()

        self._raw_events: list[dict[str, Any]] = []
        self._record_start_time: float = 0.0
        self._last_event_time: float = 0.0

        self._kb_hook = None
        self._mouse_hook = None
        self._kb_cb_ref = None
        self._mouse_cb_ref = None
        self._thread: threading.Thread | None = None
        self._play_thread: threading.Thread | None = None
        self._started_event = threading.Event()

        # Check if an existing loop macro is already saved on disk
        if self.macro_file.exists():
            self.state = "READY"

    def _set_state(self, new_state: str, message: str = ""):
        self.state = new_state
        if self.on_status_change:
            try:
                self.on_status_change(new_state, message)
            except Exception:
                pass

    # ---- Hook Callbacks ----
    def _kb_cb(self, code, wparam, lparam):
        if code >= 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            vk = int(info.vkCode)

            # 1. F11: Universal Emergency Abort
            if vk == VK_F11:
                self._handle_f11_abort()
                return 1  # Suppress default fullscreen toggle

            # 2. F10: Record toggle (Start / Stop)
            if vk == VK_F10:
                self._handle_f10_toggle()
                return 1  # Suppress default window menu bar focus

            # 3. F12: Replay (Single or Ctrl+F12 Loop)
            if vk == VK_F12:
                ctrl_down = is_ctrl_pressed()
                self._handle_f12_replay(loop=ctrl_down)
                return 1  # Suppress default browser devtools toggle

            # If recording, record key event
            if self.state == "RECORDING":
                now = time.time()
                key = _CONTROL_KEYS.get(vk)
                if key:
                    delay = max(0.0, round(now - self._last_event_time, 3)) if self._last_event_time else 0.0
                    self._raw_events.append({"t": "key", "key": key, "delay_before": delay})
                    self._last_event_time = now

        return _user32.CallNextHookEx(self._kb_hook, code, wparam, lparam)

    def _mouse_cb(self, code, wparam, lparam):
        if code >= 0 and self.state == "RECORDING":
            info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            x, y = int(info.pt.x), int(info.pt.y)
            now = time.time()

            if wparam in _MOUSE_BUTTON:
                delay = max(0.0, round(now - self._last_event_time, 3)) if self._last_event_time else 0.0
                self._raw_events.append({
                    "t": "click",
                    "x": x,
                    "y": y,
                    "button": _MOUSE_BUTTON[wparam],
                    "clicks": 1,
                    "delay_before": delay,
                })
                self._last_event_time = now
            elif wparam == WM_MOUSEWHEEL:
                clicks = _mouse_wheel_clicks(int(info.mouseData))
                if clicks:
                    delay = max(0.0, round(now - self._last_event_time, 3)) if self._last_event_time else 0.0
                    self._raw_events.append({
                        "t": "scroll",
                        "x": x,
                        "y": y,
                        "clicks": clicks,
                        "delay_before": delay,
                    })
                    self._last_event_time = now

        return _user32.CallNextHookEx(self._mouse_hook, code, wparam, lparam)

    # ---- Actions ----
    def _handle_f10_toggle(self):
        if self.state == "RECORDING":
            # Stop recording and package
            play_sound("stop_record")
            steps = list(self._raw_events)
            self._raw_events = []
            if steps:
                save_macro(self.macro_file, QUICK_MACRO_NAME, "快捷按键精灵循环宏 (F10录制/F12回放)", steps)
                self._set_state("READY", f"已录制 {len(steps)} 步动作，按 F12 重放，Ctrl+F12 循环 10 次")
            else:
                self._set_state("IDLE", "未检测到有效按键/鼠标操作")
        elif self.state in ("IDLE", "READY"):
            # Start recording
            play_sound("start_record")
            self._raw_events = []
            self._record_start_time = time.time()
            self._last_event_time = self._record_start_time
            self._set_state("RECORDING", "录制中... 完成后请再次按 F10 封包，按 F11 中止")

    def _handle_f11_abort(self):
        play_sound("abort")
        self._play_stop_flag.set()
        if self.state == "RECORDING":
            self._raw_events = []
            self._set_state("IDLE", "录制已中止并清空")
        elif self.state == "PLAYING":
            self._set_state("READY", "回放已被 F11 紧急刹车中止")

    def _handle_f12_replay(self, loop: bool = False):
        if self.state == "PLAYING":
            return
        if not self.macro_file.exists():
            play_sound("abort")
            self._set_state("IDLE", "尚未录制循环宏（请先按 F10 录制）")
            return

        try:
            macro = load_macro(self.macro_file)
            steps = macro.get("steps", [])
        except Exception as e:
            play_sound("abort")
            self._set_state("IDLE", f"宏文件损坏: {e}")
            return

        if not steps:
            play_sound("abort")
            self._set_state("IDLE", "宏步骤为空")
            return

        loop_count = 10 if loop else 1
        self._set_state("PLAYING", f"正在回放宏（循环 {loop_count} 次，按 F11 刹车）...")
        self._play_stop_flag.clear()

        def _runner():
            from .desktop_guard import execution_guard, ExecutionContext
            with execution_guard(ExecutionContext.USER_DIALOGUE, source="user:quick_macro_hotkey"):
                play_sound("play_start")
                completed_loops = 0
                for r in range(loop_count):
                    if self._play_stop_flag.is_set():
                        break
                    executed, status = play_steps(steps, speed=1.0, stop_flag=self._play_stop_flag)
                    if self._play_stop_flag.is_set() or status.startswith("[error]"):
                        break
                    completed_loops += 1

                if not self._play_stop_flag.is_set():
                    play_sound("play_finish")
                    self._set_state("READY", f"回放完成（共执行 {completed_loops} 轮循环）")
                else:
                    self._set_state("READY", f"已在第 {completed_loops + 1} 轮被 F11 中止")

        self._play_thread = threading.Thread(target=_runner, daemon=True)
        self._play_thread.start()

    # ---- Lifecycle ----
    def _unhook(self):
        if self._kb_hook:
            try:
                _user32.UnhookWindowsHookEx(self._kb_hook)
            except Exception:
                pass
            self._kb_hook = None
        if self._mouse_hook:
            try:
                _user32.UnhookWindowsHookEx(self._mouse_hook)
            except Exception:
                pass
            self._mouse_hook = None

    def _pump(self):
        self._kb_cb_ref = HOOKPROC(self._kb_cb)
        self._mouse_cb_ref = HOOKPROC(self._mouse_cb)
        self._kb_hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._kb_cb_ref, None, 0)
        self._mouse_hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_cb_ref, None, 0)
        self._started_event.set()

        if not self._kb_hook or not self._mouse_hook:
            self._unhook()
            return

        msg = wintypes.MSG()
        try:
            while not self._stop_daemon.is_set():
                if _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.005)
        finally:
            self._unhook()

    def start(self) -> None:
        """Start the background hook daemon."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_daemon.clear()
        self._started_event.clear()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        self._started_event.wait(timeout=2.0)
        if not self._kb_hook or not self._mouse_hook:
            self.stop()
            raise RuntimeError(f"安装全局按键精灵钩子失败（kb={self._kb_hook}, mouse={self._mouse_hook}）")

    def stop(self) -> None:
        """Stop daemon and cleanup."""
        self._stop_daemon.set()
        self._play_stop_flag.set()
        self._unhook()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)


# Global singleton listener for CLI / Agent tool
_ACTIVE_QUICK_DAEMON: QuickMacroDaemon | None = None


def start_quick_macro_daemon(workspace_root: Path | None = None,
                             on_status_change: Callable[[str, str], None] | None = None) -> QuickMacroDaemon:
    """Start or retrieve the active QuickMacro daemon."""
    global _ACTIVE_QUICK_DAEMON
    if _ACTIVE_QUICK_DAEMON is None:
        _ACTIVE_QUICK_DAEMON = QuickMacroDaemon(workspace_root, on_status_change)
        _ACTIVE_QUICK_DAEMON.start()
    return _ACTIVE_QUICK_DAEMON


def stop_quick_macro_daemon() -> None:
    """Stop active daemon."""
    global _ACTIVE_QUICK_DAEMON
    if _ACTIVE_QUICK_DAEMON is not None:
        _ACTIVE_QUICK_DAEMON.stop()
        _ACTIVE_QUICK_DAEMON = None
