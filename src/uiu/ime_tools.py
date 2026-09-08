"""IME / keyboard layout awareness — check & force English mode before typing.

问题：pyautogui 输入时如果系统是中文输入法（0x0804），字母键会被 IME 吃掉，
"uiuagent" 变成 "uiu阿根廷"。必须输入前检测并切到英文模式。

机制（Windows）：
- GetKeyboardLayout(thread) → 当前布局（0x0804 中文 / 0x0409 英文）
- ImmGetOpenStatus → IME 是否开启（拼音模式）
- 中文模式 → 按 Shift 切换中/英（微软拼音/搜狗等主流 IME 都是 Shift 切换）
  或者用 SendInput 模拟 VK_SHIFT 按下抬起

所有输入类工具（type_text / send_wechat / shell 里的中文输入）调用前应先 ensure_english_ime()。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

# layout ids
LANG_CHINESE = 0x0804
LANG_ENGLISH = 0x0409


def _user32():
    """Return the ctypes user32 DLL object (not a cached function)."""
    return ctypes.windll.user32


def current_ime_state() -> dict:
    """Return dict: {layout_id, layout_name, ime_open, is_chinese}."""
    u = _user32()
    hwnd = u.GetForegroundWindow()
    tid = u.GetWindowThreadProcessId(hwnd, None)
    hkl = u.GetKeyboardLayout(tid)
    layout_id = hkl & 0xFFFF

    # IME open status
    ime_open = False
    try:
        imm32 = ctypes.windll.imm32
        ctx = imm32.ImmGetContext(hwnd)
        if ctx:
            ime_open = bool(imm32.ImmGetOpenStatus(ctx))
            imm32.ImmReleaseContext(hwnd, ctx)
    except Exception:
        pass

    names = {
        0x0804: "中文(简体，中国)",
        0x0404: "中文(台湾)",
        0x0409: "英文(美国)",
        0x0809: "英文(英国)",
        0x0411: "日文",
    }
    return {
        "layout_id": layout_id,
        "layout_name": names.get(layout_id, f"0x{layout_id:04X}"),
        "ime_open": ime_open,
        "is_chinese": layout_id in (0x0804, 0x0404, 0x0804 + 0x1000),
    }


def is_english_mode() -> bool:
    """True if typing ASCII will produce ASCII (English layout & IME closed/English mode)."""
    state = current_ime_state()
    if not state["is_chinese"]:
        return True
    # Chinese layout but IME closed → English mode (in Chinese IME, closed = direct English)
    return not state["ime_open"]


def ensure_english_ime(quiet: bool = True) -> dict:
    """Ensure the system is in English input mode. Returns state after attempt.

    Strategy:
    1. Check current state.
    2. If Chinese layout + IME open (pinyin mode) → press Shift to toggle to English.
    """
    from .desktop_guard import check_desktop_action_allowed
    allowed, reason = check_desktop_action_allowed("ensure_english_ime")
    if not allowed:
        return current_ime_state()

    import pyautogui

    state = current_ime_state()
    if not quiet:
        print(f"[ime] 当前: {state['layout_name']} (IME {'开' if state['ime_open'] else '关'})")

    if not state["is_chinese"] or not state["ime_open"]:
        return current_ime_state()  # already English-safe

    # Chinese IME open → press Shift to toggle Chinese/English mode (mainstream IMEs)
    if not quiet:
        print("[ime] 中文模式 → 按 Shift 切换到英文")
    pyautogui.press("shift")
    time.sleep(0.3)

    # re-check
    state2 = current_ime_state()
    if not quiet:
        print(f"[ime] 切换后: {state2['layout_name']} (IME {'开' if state2['ime_open'] else '关'})")

    # if IME still open (Shift didn't work or IME uses other toggle) → Alt+Shift layout switch
    if state2["is_chinese"] and state2["ime_open"]:
        if not quiet:
            print("[ime] Shift 无效 → Alt+Shift 切换布局")
        pyautogui.hotkey("alt", "shift")
        time.sleep(0.4)
        state2 = current_ime_state()
        if not quiet:
            print(f"[ime] 布局切换后: {state2['layout_name']} (IME {'开' if state2['ime_open'] else '关'})")

    return state2


# tool definition

IME_STATE_DEF = {
    "type": "function",
    "function": {
        "name": "ime_state",
        "description": "检查当前输入法状态（中文/英文、IME 开/关）。输入文字前应调用确保是英文模式，避免中文输入法把字母吃成汉字。",
        "parameters": {"type": "object", "properties": {}},
    },
}

IME_ENSURE_DEF = {
    "type": "function",
    "function": {
        "name": "ensure_english_ime",
        "description": "强制切到英文输入模式（按 Shift 或 Alt+Shift）。输入 ASCII 文字前必须先调用，防止中文输入法把字母变汉字（如 uiuagent → uiu阿根廷）。",
        "parameters": {"type": "object", "properties": {}},
    },
}

IME_TOOLS: dict[str, dict] = {
    "ime_state": {"def": IME_STATE_DEF, "fn": lambda: str(current_ime_state())},
    "ensure_english_ime": {"def": IME_ENSURE_DEF, "fn": lambda: str(ensure_english_ime(quiet=False))},
}


def ime_tool_defs() -> list[dict]:
    return [t["def"] for t in IME_TOOLS.values()]


def call_ime_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in IME_TOOLS:
        return f"[error] unknown ime tool: {name}"
    fn = IME_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"