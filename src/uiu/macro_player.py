"""Macro player — replay recorded steps through existing gui_primitives.

逐条执行宏步骤，全部复用 gui_primitives（零新执行引擎）：
- click → mouse_click / scroll → mouse_scroll / key → press_key
- hotkey → press_hotkey / type → paste_text / wait → sleep
- delay_before/speed 控制时序；F9 / FAILSAFE / stop_flag 可中止
"""

from __future__ import annotations

import time

from .gui_primitives import mouse_click, mouse_scroll, paste_text, press_hotkey, press_key

# 中止检测：F9（与录制同键）；pyautogui FAILSAFE 在 gui_primitives 内部已生效
_STOP_VK = 0x78


def _stop_pressed() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(_STOP_VK) & 0x8000)
    except Exception:
        return False


def play_steps(steps: list[dict], speed: float = 1.0,
               stop_flag=None, start: int = 0, end: int | None = None,
               pause_between: float | None = None) -> tuple[int, str]:
    """Execute steps in order. Returns (executed_count, status).

    - speed: 倍速（2.0 = 间隔减半）
    - stop_flag: threading.Event，置位即停（供外部中止）
    - start/end: 步数区间（1 起，含），调试用
    - pause_between: 非 None 时覆盖 delay_before（固定步间延迟）
    """
    if speed <= 0:
        return 0, "[error] speed 必须为正数"
    total = len(steps)
    if total == 0:
        return 0, "(空宏，无步骤)"
    s = max(1, int(start or 1))
    e = min(total, int(end) if end else total)
    if s > e or s > total:
        return 0, f"[error] 无效步数区间 {start}-{end}（共 {total} 步）"
    executed = 0
    for i in range(s - 1, e):
        if stop_flag is not None and stop_flag.is_set():
            return executed, f"(已中止：第 {i + 1} 步前 stop_flag 置位)"
        if _stop_pressed():
            return executed, f"(已中止：F9 在第 {i + 1} 步前按下)"
        step = steps[i]
        delay = pause_between if pause_between is not None else step.get("delay_before", 0.0)
        if delay and delay > 0:
            time.sleep(delay / speed)
        if stop_flag is not None and stop_flag.is_set():
            return executed, f"(已中止：第 {i + 1} 步等待后)"
        err = _exec_step(step)
        if err:
            return executed, err
        executed += 1
    return executed, f"(完成 {executed} 步)"


def _exec_step(step: dict) -> str | None:
    """Execute one step; returns error string or None on success."""
    t = step.get("t")
    try:
        if t == "click":
            out = mouse_click(x=int(step.get("x", 0)), y=int(step.get("y", 0)),
                              button=step.get("button", "left"), clicks=int(step.get("clicks", 1)))
        elif t == "scroll":
            out = mouse_scroll(clicks=int(step.get("clicks", 0)),
                               x=step.get("x"), y=step.get("y"))
        elif t == "key":
            out = press_key(key_name=str(step.get("key", "")))
        elif t == "hotkey":
            out = press_hotkey(keys=[str(k) for k in step.get("keys", [])])
        elif t == "type":
            out = paste_text(text=str(step.get("text", "")), clear_before=bool(step.get("clear_before", False)))
        elif t == "wait":
            time.sleep(max(0.0, float(step.get("sec", 1))))
            return None
        else:
            return f"[error] 未知步骤类型: {t}"
    except Exception as e:
        return f"[error] 步骤 {t} 执行异常: {type(e).__name__}: {e}"
    if out and out.startswith("[error]"):
        return out
    return None


def play_macro_file(path, speed: float = 1.0, stop_flag=None,
                    start: int = 0, end: int | None = None,
                    pause_between: float | None = None) -> tuple[int, str]:
    """Load a macro file and play it. Returns (executed, status)."""
    from .macro_recorder import load_macro
    try:
        macro = load_macro(path)
    except Exception as e:
        return 0, f"[error] 加载宏失败: {e}"
    return play_steps(macro.get("steps", []), speed=speed, stop_flag=stop_flag,
                      start=start, end=end, pause_between=pause_between)
