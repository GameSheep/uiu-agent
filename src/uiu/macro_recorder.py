"""Macro recorder — capture mouse/keyboard events as reusable steps.

零依赖实现（ctypes 低级钩子，无 pynput）：
- WH_MOUSE_LL + WH_KEYBOARD_LL 全局钩子跑在独立线程的消息泵里
- 只记关键操作：点击(坐标/键)、滚轮、控制键(enter/tab/方向/F 键…)
- 可打印字符不逐键录（IME 组合不可靠）→ 用 F2 插文本步骤（见 record UI）
- F9 停止录制（不录成步骤）；支持 timeout 自动停

录制线程把事件塞进 queue；主线程消费累积成 steps。
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

# ---- win32 常量 ----
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_MOUSEWHEEL = 0x020A
WM_MOUSEMOVE = 0x0200

VK_F9 = 0x78
VK_F2 = 0x71

# 控制键：录成 key 步骤（可打印字符不录）
_CONTROL_KEYS = {
    0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x1B: "esc",
    0x20: "space", 0x2D: "insert", 0x2E: "delete", 0x24: "home",
    0x23: "end", 0x21: "pageup", 0x22: "pagedown",
    0x25: "left", 0x26: "up", 0x27: "right", 0x28: "down",
    0x2C: "printscreen", 0x13: "pause",
}
for _i in range(0x70, 0x88):  # F1-F24
    _CONTROL_KEYS[_i] = f"f{_i - 0x6F}"

_MOUSE_BUTTON = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right", WM_MBUTTONDOWN: "middle"}

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_user32 = ctypes.windll.user32
_user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = ctypes.c_ssize_t
_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wintypes.DWORD]
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


def _mouse_wheel_clicks(mouse_data: int) -> int:
    """WM_MOUSEWHEEL 的 delta（±120 的倍数）→ 滚动单位数（负=向下）。"""
    delta = ctypes.c_short(mouse_data >> 16).value
    return delta // 120


def _synthesize(event: dict) -> dict:
    """Convert one raw event into a macro step (pure, testable).

    Raw events: {"type":"down","vk":..} | {"type":"click","x":..,"y":..,"button":..}
                | {"type":"wheel","x":..,"y":..,"clicks":n}
    Returns a step dict or None (F9 / 可打印字符 / 其他忽略).
    """
    t = event.get("type")
    if t == "down":
        vk = event.get("vk", 0)
        if vk == VK_F9:
            return {"stop": True}
        key = _CONTROL_KEYS.get(vk)
        if key is None:
            return None  # 可打印字符不逐键录（IME）
        return {"t": "key", "key": key}
    if t == "click":
        return {"t": "click", "x": int(event["x"]), "y": int(event["y"]),
                "button": event.get("button", "left")}
    if t == "wheel":
        return {"t": "scroll", "clicks": event["clicks"], "x": int(event["x"]), "y": int(event["y"])}
    return None


class MacroRecorder:
    """Blocking recorder: run() until F9/timeout, returns steps."""

    def __init__(self, stop_key_vk: int = VK_F9, timeout: float = 0):
        self.stop_vk = stop_key_vk
        self.timeout = timeout
        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._hook = None
        self._kb_hook = None
        self._mouse_hook = None
        self._thread = None
        self._mouse_x = 0
        self._mouse_y = 0

    # ---- 钩子回调（在钩子线程里，只塞队列不做重活） ----
    def _kb_cb(self, code, wparam, lparam):
        if code >= 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            info = ctypes.cast(lparam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
            self._events.put({"type": "down", "vk": int(info.vkCode), "ts": time.time()})
        return _user32.CallNextHookEx(self._kb_hook, code, wparam, lparam)

    def _mouse_cb(self, code, wparam, lparam):
        if code >= 0:
            info = ctypes.cast(lparam, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
            x, y = int(info.pt.x), int(info.pt.y)
            self._mouse_x, self._mouse_y = x, y
            if wparam in _MOUSE_BUTTON:
                self._events.put({"type": "click", "x": x, "y": y,
                                  "button": _MOUSE_BUTTON[wparam], "ts": time.time()})
            elif wparam == WM_MOUSEWHEEL:
                clicks = _mouse_wheel_clicks(int(info.mouseData))
                if clicks:
                    self._events.put({"type": "wheel", "x": x, "y": y,
                                      "clicks": clicks, "ts": time.time()})
        return _user32.CallNextHookEx(self._mouse_hook, code, wparam, lparam)

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

    # ---- 消息泵线程：必须由安装钩子的同一线程负责派发，否则导致 Windows 系统级按键卡顿丢键 ----
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
            while not self._stop.is_set():
                if _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
                else:
                    time.sleep(0.005)
        finally:
            self._unhook()

    def start(self) -> None:
        """Start the message-pump thread which installs hooks on its own message loop."""
        import atexit
        atexit.register(self.stop)
        self._started_event = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        self._started_event.wait(timeout=2.0)
        if not self._kb_hook or not self._mouse_hook:
            self.stop()
            raise RuntimeError(f"安装全局钩子失败（kb={self._kb_hook}, mouse={self._mouse_hook}）")

    def stop(self) -> None:
        self._stop.set()
        self._unhook()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def run(self) -> tuple[list[dict], bool]:
        """Block until stop key / timeout. Returns (steps, aborted_by_key)."""
        self._stop.clear()
        self.start()
        steps: list[dict] = []
        prev_ts: float | None = None
        start = time.time()
        aborted = False
        try:
            while not self._stop.is_set():
                if self.timeout and time.time() - start > self.timeout:
                    break
                try:
                    ev = self._events.get(timeout=0.05)
                except queue.Empty:
                    continue
                step = _synthesize(ev)
                if step is None:
                    continue
                if step.pop("stop", False):
                    aborted = True
                    break
                ts = ev.get("ts", time.time())
                step["delay_before"] = round(ts - prev_ts, 2) if prev_ts is not None else 0.0
                prev_ts = ts
                steps.append(step)
        finally:
            self.stop()
        return steps, aborted


def _now_ms() -> float:
    return time.time()


def save_macro(path: Path, name: str, description: str, steps: list[dict]) -> str:
    """Persist a macro to workspace/macros/<name>.json."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "description": description,
        "created": _now_ms(),
        "steps": steps,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_macro(path: Path) -> dict:
    """Load + validate a macro file. Raises ValueError on bad shape."""
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise ValueError(f"宏文件格式非法: {path}")
    return data


def macros_dir(workspace: Path) -> Path:
    d = Path(workspace) / "macros"
    d.mkdir(parents=True, exist_ok=True)
    return d
