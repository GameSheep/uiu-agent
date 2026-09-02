"""Screen automation tools — click buttons by NAME using OCR (no vision model).

链路：截图(PyAutoGUI) → OCR(RapidOCR) → 按文本找坐标 → 点击(PyAutoGUI)

注册为 agent 工具后，用户说"点击网页上的提交按钮"，agent 调 click_text。
"""

from __future__ import annotations

import time


def _ocr_engine():
    """Lazy-import RapidOCR (heavy first load)."""
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _screenshot() -> str:
    """Take a full-screen screenshot, save to temp PNG, return path."""
    import tempfile
    from pathlib import Path
    import pyautogui
    tmp = Path(tempfile.gettempdir()) / "uiu_screen.png"
    img = pyautogui.screenshot()
    img.save(str(tmp))
    return str(tmp)


def _ocr_image(path: str) -> list[dict]:
    """OCR an image. Returns [{text, x, y, w, h, score, cx, cy}]."""
    ocr = _ocr_engine()
    result, _ = ocr(path)
    items = []
    for item in result or []:
        box, text, score = item
        x1, y1 = box[0]
        x2, y2 = box[2]
        items.append({
            "text": text,
            "x": int(x1), "y": int(y1),
            "w": int(x2 - x1), "h": int(y2 - y1),
            "score": float(score),
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
        })
    return items


def _find(items: list[dict], text: str) -> list[dict]:
    """Find OCR items whose text matches (exact or contains)."""
    text = text.strip()
    exact = [i for i in items if i["text"] == text]
    if exact:
        return exact
    return [i for i in items if text in i["text"] or i["text"] in text]


# ---------- tools ----------

def screen_read_text() -> str:
    """OCR the whole screen and return all visible text (like a screen reader)."""
    path = _screenshot()
    items = _ocr_image(path)
    if not items:
        return "(屏幕上没有识别到文字)"
    lines = []
    for it in items:
        lines.append(f"  '{it['text']}' @ ({it['x']},{it['y']})")
    return "屏幕文字:\n" + "\n".join(lines)


def click_text(text: str, click_count: int = 1) -> str:
    """Click a button/element by its visible text (OCR-based, no vision model).

    Screenshots the screen, finds text, clicks its center. Returns what happened.
    """
    import pyautogui
    path = _screenshot()
    items = _ocr_image(path)
    matches = _find(items, text)
    if not matches:
        # maybe partially visible — list candidates
        cands = [it["text"] for it in items if len(it["text"]) <= len(text) + 4]
        hint = f" 相近文字: {cands[:8]}" if cands else ""
        return f"[error] 屏幕上没找到 '{text}'{hint}"

    # prefer highest score
    best = max(matches, key=lambda i: i["score"])
    cx, cy = int(best["cx"]), int(best["cy"])
    pyautogui.moveTo(cx, cy, duration=0.2)
    for _ in range(max(1, click_count)):
        pyautogui.click()
        time.sleep(0.05)
    return f"[ok] 已点击 '{best['text']}' 位置 ({cx},{cy})"


def type_text(text: str, interval: float = 0.02) -> str:
    """Type text into the focused input (after click_text focuses it).

    中文安全：走剪贴板粘贴（typewrite 打中文会乱码）。
    """
    import pyautogui
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        # contains CJK → clipboard paste
        try:
            from .system_tools import clipboard_set
            clipboard_set(text)
            pyautogui.hotkey("ctrl", "v")
            return f"[ok] 已输入 {len(text)} 字符（剪贴板）"
        except Exception:
            pass
    pyautogui.write(text, interval=interval)
    return f"[ok] 已输入 {len(text)} 字符"


def press_key(keys: str) -> str:
    """Press a key or combo (e.g. 'enter', 'ctrl+s')."""
    import pyautogui
    parts = keys.lower().split("+")
    if len(parts) > 1:
        pyautogui.hotkey(*parts)
    else:
        pyautogui.press(parts[0])
    return f"[ok] 按键 {keys}"


# ---------- tool definitions ----------

CLICK_TEXT_DEF = {
    "type": "function",
    "function": {
        "name": "click_text",
        "description": "点击屏幕上可见文字对应的按钮/元素。截图→OCR→找文字→点击。适合'点击提交/确定/登录按钮'这类命令。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "按钮上显示的文字，如 '提交'"},
                "click_count": {"type": "integer", "description": "点击次数（默认1）"},
            },
            "required": ["text"],
        },
    },
}

SCREEN_READ_DEF = {
    "type": "function",
    "function": {
        "name": "screen_read_text",
        "description": "读取整个屏幕的可见文字（OCR）。用户问'屏幕上有什么'或需要找元素时用。",
        "parameters": {"type": "object", "properties": {}},
    },
}

TYPE_TEXT_DEF = {
    "type": "function",
    "function": {
        "name": "type_text",
        "description": "在当前聚焦的输入框输入文字（先用 click_text 点击输入框聚焦）。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "interval": {"type": "number", "description": "每字符间隔秒（默认0.02）"},
            },
            "required": ["text"],
        },
    },
}

PRESS_KEY_DEF = {
    "type": "function",
    "function": {
        "name": "press_key",
        "description": "按键或组合键，如 'enter'、'ctrl+s'、'alt+tab'。",
        "parameters": {
            "type": "object",
            "properties": {"keys": {"type": "string"}},
            "required": ["keys"],
        },
    },
}


SCREEN_TOOLS: dict[str, dict] = {
    "click_text": {"def": CLICK_TEXT_DEF, "fn": click_text},
    "screen_read_text": {"def": SCREEN_READ_DEF, "fn": screen_read_text},
    "type_text": {"def": TYPE_TEXT_DEF, "fn": type_text},
    "press_key": {"def": PRESS_KEY_DEF, "fn": press_key},
}


def screen_tool_defs() -> list[dict]:
    return [t["def"] for t in SCREEN_TOOLS.values()]


def call_screen_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in SCREEN_TOOLS:
        return f"[error] unknown screen tool: {name}"
    fn = SCREEN_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"