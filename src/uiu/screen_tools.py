"""Screen automation tools — click buttons by NAME using OCR (no vision model).

链路：截图(dxcam/screen-ocr) → OCR(Windows WinRT) → 按文本找坐标 → 点击(PyAutoGUI)

性能：
- 全屏幕 OCR: < 1秒 (WinRT 原生引擎)
- 区域 OCR: < 0.1秒
- 备用: RapidOCR (如果 WinRT 不可用)
"""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Optional


# ---------- OCR engine (WinRT primary, RapidOCR fallback) ----------

_winrt_reader = None
_winrt_lock = threading.Lock()


def _get_winrt_reader():
    """Get or create WinRT OCR reader (fast, native Windows OCR)."""
    global _winrt_reader
    if _winrt_reader is not None:
        return _winrt_reader

    with _winrt_lock:
        if _winrt_reader is not None:
            return _winrt_reader
        try:
            from screen_ocr import Reader
            _winrt_reader = Reader.create_fast_reader()
            return _winrt_reader
        except ImportError:
            return None


def _ocr_winrt_full() -> list[dict]:
    """OCR full screen using WinRT (fast, < 1s)."""
    reader = _get_winrt_reader()
    if reader is None:
        return []

    # Retry up to 2 times on failure (DXcam can fail occasionally)
    for attempt in range(2):
        try:
            result = reader.read_screen()
            break
        except Exception:
            if attempt == 0:
                time.sleep(0.2)
                continue
            return []
    else:
        return []

    items = []
    if not result or not hasattr(result, "result"):
        return items

    ocr_result = result.result
    if not hasattr(ocr_result, "lines"):
        return items

    for line in ocr_result.lines:
        if not hasattr(line, "words") or not line.words:
            continue

        # Build line text from words
        words = line.words
        text = "".join(w.text for w in words if hasattr(w, "text")).strip()
        if not text:
            continue

        # Calculate bounding box from words
        first_word = words[0]
        last_word = words[-1]

        if hasattr(first_word, "left") and hasattr(first_word, "top"):
            x1 = first_word.left
            y1 = first_word.top
            x2 = last_word.left + last_word.width
            y2 = first_word.top + first_word.height
        else:
            continue

        items.append({
            "text": text,
            "x": int(x1), "y": int(y1),
            "w": int(x2 - x1), "h": int(y2 - y1),
            "score": 1.0,
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
        })

    return items


def _ocr_winrt_region(x: int, y: int, w: int, h: int) -> list[dict]:
    """OCR a region using WinRT (very fast, < 0.2s)."""
    reader = _get_winrt_reader()
    if reader is None:
        return []

    # Take screenshot of region
    import pyautogui
    from PIL import Image

    img = pyautogui.screenshot(region=(x, y, w, h))

    # OCR the image directly (pass PIL Image, not path)
    result = reader.read_image(img)
    items = []

    if not result or not hasattr(result, "result"):
        return items

    ocr_result = result.result
    if not hasattr(ocr_result, "lines"):
        return items

    for line in ocr_result.lines:
        if not hasattr(line, "words") or not line.words:
            continue

        # Build line text from words
        words = line.words
        text = "".join(w.text for w in words if hasattr(w, "text")).strip()
        if not text:
            continue

        # Calculate bounding box from words (region-relative → screen)
        first_word = words[0]
        last_word = words[-1]

        if hasattr(first_word, "left") and hasattr(first_word, "top"):
            sx1 = first_word.left + x
            sy1 = first_word.top + y
            sx2 = last_word.left + last_word.width + x
            sy2 = first_word.top + first_word.height + y
        else:
            continue

        items.append({
            "text": text,
            "x": int(sx1), "y": int(sy1),
            "w": int(sx2 - sx1), "h": int(sy2 - sy1),
            "score": 1.0,
            "cx": (sx1 + sx2) / 2,
            "cy": (sy1 + sy2) / 2,
        })

    return items


# ---------- RapidOCR fallback (if WinRT not available) ----------

_rapidocr_engine = None
_rapidocr_lock = threading.Lock()


def _get_rapidocr_engine():
    """Get or create RapidOCR engine (fallback)."""
    global _rapidocr_engine
    if _rapidocr_engine is not None:
        return _rapidocr_engine

    with _rapidocr_lock:
        if _rapidocr_engine is not None:
            return _rapidocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapidocr_engine = RapidOCR()
            return _rapidocr_engine
        except ImportError:
            return None


def _ocr_rapidocr_full() -> list[dict]:
    """OCR full screen using RapidOCR (fallback, slower)."""
    engine = _get_rapidocr_engine()
    if engine is None:
        return []

    import pyautogui
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "uiu_screen.png"
    img = pyautogui.screenshot()
    img.save(str(tmp))

    result, _ = engine(str(tmp))
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


# ---------- unified OCR API ----------

def _ocr_full_screen() -> list[dict]:
    """OCR full screen (WinRT preferred, RapidOCR fallback)."""
    # Try WinRT first (fast)
    items = _ocr_winrt_full()
    if items:
        return items

    # Fallback to RapidOCR
    return _ocr_rapidocr_full()


def _ocr_region(x: int, y: int, w: int, h: int) -> list[dict]:
    """OCR a region (WinRT preferred)."""
    items = _ocr_winrt_region(x, y, w, h)
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
    items = _ocr_full_screen()
    if not items:
        return "(屏幕上没有识别到文字)"
    lines = []
    for it in items:
        lines.append(f"  '{it['text']}' @ ({it['x']},{it['y']})")
    return "屏幕文字:\n" + "\n".join(lines)


def click_text(text: str, click_count: int = 1) -> str:
    """Click a button/element by its visible text (OCR-based, no vision model)."""
    import pyautogui
    items = _ocr_full_screen()
    matches = _find(items, text)
    if not matches:
        cands = [it["text"] for it in items if len(it["text"]) <= len(text) + 4]
        hint = f" 相近文字: {cands[:8]}" if cands else ""
        return f"[error] 屏幕上没找到 '{text}'{hint}"

    best = max(matches, key=lambda i: i["score"])
    cx, cy = int(best["cx"]), int(best["cy"])
    pyautogui.moveTo(cx, cy, duration=0.2)
    for _ in range(max(1, click_count)):
        pyautogui.click()
        time.sleep(0.05)
    return f"[ok] 已点击 '{best['text']}' 位置 ({cx},{cy})"


def type_text(text: str, interval: float = 0.02) -> str:
    """Type text into the focused input (after click_text focuses it)."""
    import pyautogui
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if has_cjk:
        try:
            from .system_tools import clipboard_set
            clipboard_set(text)
            pyautogui.hotkey("ctrl", "v")
            return f"[ok] 已输入 {len(text)} 字符（剪贴板）"
        except Exception:
            pass
    else:
        try:
            from .ime_tools import ensure_english_ime
            ensure_english_ime()
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


def ocr_region(x: int, y: int, w: int, h: int) -> str:
    """OCR a specific region of the screen (fast, < 0.5s)."""
    items = _ocr_region(x, y, w, h)
    if not items:
        return "(区域内没有识别到文字)"
    lines = [f"区域 ({x},{y},{w},{h}) 文字:"]
    for it in items:
        lines.append(f"  '{it['text']}' @ ({it['x']},{it['y']})")
    return "\n".join(lines)


def click_in_region(text: str, region_x: int, region_y: int, region_w: int, region_h: int) -> str:
    """Find and click text within a specific screen region (fast)."""
    import pyautogui
    items = _ocr_region(region_x, region_y, region_w, region_h)
    matches = _find(items, text)
    if not matches:
        return f"[error] 区域内没找到 '{text}'"
    best = max(matches, key=lambda i: i["score"])
    screen_cx = int(best["cx"])
    screen_cy = int(best["cy"])
    pyautogui.moveTo(screen_cx, screen_cy, duration=0.1)
    pyautogui.click()
    return f"[ok] 已点击 '{best['text']}' @ ({screen_cx},{screen_cy})"


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

OCR_REGION_DEF = {
    "type": "function",
    "function": {
        "name": "ocr_region",
        "description": "OCR 识别屏幕指定区域的文字（快速，<0.5秒）。适合小范围识别。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "区域左上角 X 坐标"},
                "y": {"type": "integer", "description": "区域左上角 Y 坐标"},
                "w": {"type": "integer", "description": "区域宽度"},
                "h": {"type": "integer", "description": "区域高度"},
            },
            "required": ["x", "y", "w", "h"],
        },
    },
}

CLICK_IN_REGION_DEF = {
    "type": "function",
    "function": {
        "name": "click_in_region",
        "description": "在指定区域内查找并点击文字（快速）。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要点击的文字"},
                "region_x": {"type": "integer", "description": "区域左上角 X"},
                "region_y": {"type": "integer", "description": "区域左上角 Y"},
                "region_w": {"type": "integer", "description": "区域宽度"},
                "region_h": {"type": "integer", "description": "区域高度"},
            },
            "required": ["text", "region_x", "region_y", "region_w", "region_h"],
        },
    },
}


SCREEN_TOOLS: dict[str, dict] = {
    "click_text": {"def": CLICK_TEXT_DEF, "fn": click_text},
    "screen_read_text": {"def": SCREEN_READ_DEF, "fn": screen_read_text},
    "type_text": {"def": TYPE_TEXT_DEF, "fn": type_text},
    "press_key": {"def": PRESS_KEY_DEF, "fn": press_key},
    "ocr_region": {"def": OCR_REGION_DEF, "fn": ocr_region},
    "click_in_region": {"def": CLICK_IN_REGION_DEF, "fn": click_in_region},
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
