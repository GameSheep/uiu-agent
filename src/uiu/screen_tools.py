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
            # Pre-initialize RapidOCR/onnxruntime first to avoid Windows DirectX DLL initialization conflict
            try:
                _get_rapidocr_engine()
            except Exception:
                pass
            from screen_ocr import Reader
            _winrt_reader = Reader.create_fast_reader()
            return _winrt_reader
        except Exception:
            return None


def safe_screenshot(region: tuple[int, int, int, int] | None = None):
    """Safely capture a screenshot, ensuring interactive desktop attachment.
    Prevents 'OSError: screen grab failed' in background/service/pytest threads,
    with zero disk I/O and resilient fallback.
    """
    try:
        from .window_manager import ensure_default_desktop
        ensure_default_desktop()
    except Exception:
        pass

    import pyautogui
    from PIL import Image

    if region is not None:
        rx, ry, rw, rh = region
        if rw <= 0 or rh <= 0:
            return Image.new("RGB", (max(1, int(rw)), max(1, int(rh))), (255, 255, 255))
        region_param = (int(rx), int(ry), int(rw), int(rh))
    else:
        region_param = None

    try:
        return pyautogui.screenshot(region=region_param)
    except Exception:
        try:
            from .window_manager import ensure_default_desktop
            ensure_default_desktop()
            return pyautogui.screenshot(region=region_param)
        except Exception:
            w = region_param[2] if region_param else 1920
            h = region_param[3] if region_param else 1080
            return Image.new("RGB", (max(1, int(w)), max(1, int(h))), (255, 255, 255))


def _parse_winrt_lines(ocr_result, offset_x: int = 0, offset_y: int = 0) -> list[dict]:

    """Parse WinRT OCR lines into word-level and line-level elements with exact bounds."""
    items = []
    if not hasattr(ocr_result, "lines"):
        return items

    for line in ocr_result.lines:
        if not hasattr(line, "words") or not line.words:
            continue

        words = line.words
        text = "".join(w.text for w in words if hasattr(w, "text")).strip()
        if not text:
            continue

        parsed_words = []
        for w in words:
            if hasattr(w, "left") and hasattr(w, "top"):
                wx = w.left + offset_x
                wy = w.top + offset_y
                ww = getattr(w, "width", 0)
                wh = getattr(w, "height", 0)
                parsed_words.append({
                    "text": getattr(w, "text", ""),
                    "x": int(round(wx)),
                    "y": int(round(wy)),
                    "w": int(round(ww)),
                    "h": int(round(wh)),
                    "cx": float(wx + ww / 2.0),
                    "cy": float(wy + wh / 2.0),
                    "score": 1.0,
                })

        if not parsed_words:
            continue

        x1 = min(w["x"] for w in parsed_words)
        y1 = min(w["y"] for w in parsed_words)
        x2 = max(w["x"] + w["w"] for w in parsed_words)
        y2 = max(w["y"] + w["h"] for w in parsed_words)

        items.append({
            "text": text,
            "x": int(x1),
            "y": int(y1),
            "w": int(x2 - x1),
            "h": int(y2 - y1),
            "score": 1.0,
            "cx": float((x1 + x2) / 2.0),
            "cy": float((y1 + y2) / 2.0),
            "words": parsed_words,
        })

    return items


def _ocr_winrt_full() -> list[dict]:
    """OCR full screen using WinRT (fast, < 1s)."""
    try:
        from .window_manager import ensure_default_desktop
        ensure_default_desktop()
    except Exception:
        pass

    try:
        reader = _get_winrt_reader()
    except Exception:
        return []
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

    if not result or not hasattr(result, "result"):
        return []

    return _parse_winrt_lines(result.result, offset_x=0, offset_y=0)


def _ocr_winrt_region(x: int, y: int, w: int, h: int) -> list[dict]:
    """OCR a region using WinRT (fast, < 0.2s) with RapidOCR fallback."""
    try:
        from .window_manager import ensure_default_desktop
        ensure_default_desktop()
    except Exception:
        pass

    try:
        reader = _get_winrt_reader()
    except Exception:
        reader = None

    if reader is None:
        return _ocr_region_rapidocr(x, y, w, h)

    # Take screenshot of region safely
    img = safe_screenshot(region=(x, y, w, h))

    # OCR the image directly (pass PIL Image, not path)
    result = reader.read_image(img)
    if not result or not hasattr(result, "result"):
        return []

    return _parse_winrt_lines(result.result, offset_x=x, offset_y=y)



# ---------- RapidOCR fallback (if WinRT not available) ----------

_rapidocr_engine = None
_rapidocr_lock = threading.Lock()


def _get_rapidocr_engine():
    """Get or create RapidOCR engine (with use_angle_cls=False for faster screen OCR)."""
    global _rapidocr_engine
    if _rapidocr_engine is not None:
        return _rapidocr_engine

    with _rapidocr_lock:
        if _rapidocr_engine is not None:
            return _rapidocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _rapidocr_engine = RapidOCR(use_angle_cls=False)
            return _rapidocr_engine
        except Exception:
            return None


def _ocr_rapidocr_full() -> list[dict]:
    """OCR full screen using RapidOCR (fallback, slower)."""
    engine = _get_rapidocr_engine()
    if engine is None:
        return []

    import numpy as np
    img = safe_screenshot()
    img_np = np.array(img)


    result, _ = engine(img_np)
    items = []
    for item in result or []:
        box, text, score = item
        x1, y1 = box[0]
        x2, y2 = box[2]
        bw = x2 - x1
        bh = y2 - y1
        words = []
        n_chars = len(text)
        if n_chars > 0:
            char_w = bw / n_chars
            for idx, ch in enumerate(text):
                cw_x = x1 + idx * char_w
                words.append({
                    "text": ch,
                    "x": int(cw_x),
                    "y": int(y1),
                    "w": int(char_w),
                    "h": int(bh),
                    "cx": float(cw_x + char_w / 2.0),
                    "cy": float((y1 + y2) / 2.0),
                    "score": float(score),
                })
        items.append({
            "text": text,
            "x": int(x1), "y": int(y1),
            "w": int(bw), "h": int(bh),
            "score": float(score),
            "cx": (x1 + x2) / 2,
            "cy": (y1 + y2) / 2,
            "words": words,
        })
    return items


def _ocr_region_rapidocr(x: int, y: int, w: int, h: int) -> list[dict]:
    """OCR a sub-region using RapidOCR (100% in-memory, zero disk I/O, high Chinese accuracy)."""
    engine = _get_rapidocr_engine()
    if engine is None:
        return []

    import numpy as np
    img = safe_screenshot(region=(x, y, w, h))
    img_np = np.array(img)


    result, _ = engine(img_np)
    items = []
    for item in result or []:
        box, text, score = item
        x1, y1 = box[0]
        x2, y2 = box[2]
        bw = x2 - x1
        bh = y2 - y1
        words = []
        n_chars = len(text)
        if n_chars > 0:
            char_w = bw / n_chars
            for idx, ch in enumerate(text):
                cw_x = x1 + x + idx * char_w
                words.append({
                    "text": ch,
                    "x": int(cw_x),
                    "y": int(y1 + y),
                    "w": int(char_w),
                    "h": int(bh),
                    "cx": float(cw_x + char_w / 2.0),
                    "cy": float((y1 + y2) / 2.0 + y),
                    "score": float(score),
                })
        items.append({
            "text": text,
            "x": int(x1 + x), "y": int(y1 + y),
            "w": int(bw), "h": int(bh),
            "score": float(score),
            "cx": (x1 + x2) / 2 + x,
            "cy": (y1 + y2) / 2 + y,
            "words": words,
        })
    return items


# ---------- unified OCR API ----------

def _ocr_full_screen(engine: str = "auto") -> list[dict]:
    """OCR full screen.
    engine: 'auto' (WinRT if available, RapidOCR fallback) | 'rapidocr' | 'winrt'
    """
    if engine == "rapidocr":
        return _ocr_rapidocr_full()
    if engine == "winrt":
        return _ocr_winrt_full()
    # Try WinRT first (fast)
    items = _ocr_winrt_full()
    if items:
        return items
    return _ocr_rapidocr_full()


def _screenshot(path: str | None = None) -> str:
    """Take a full-screen screenshot, save to a temp PNG, return its path."""
    import tempfile
    save_path = path or str(Path(tempfile.gettempdir()) / "uiu_screenshot.png")
    safe_screenshot().save(save_path)
    return save_path



def _ocr_image(image_path: str) -> list[dict]:
    """OCR a saved screenshot file (RapidOCR). Items use text/x/y/w/h/score/cx/cy."""
    engine = _get_rapidocr_engine()
    if engine is None:
        return []
    result, _ = engine(str(image_path))
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


def _ocr_region(x: int, y: int, w: int, h: int, engine: str = "auto") -> list[dict]:
    """OCR a region.
    engine: 'auto' | 'rapidocr' (high Chinese accuracy) | 'winrt' (fast, sub-100ms)
    """
    if engine == "rapidocr":
        return _ocr_region_rapidocr(x, y, w, h)
    if engine == "winrt":
        return _ocr_winrt_region(x, y, w, h)
    items = _ocr_winrt_region(x, y, w, h)
    return items


def match_text_element(items: list[dict], target_text: str, exact: bool = False) -> dict | None:
    """Find the best matching element with word-level zero-drift center coordinates."""
    target = target_text.strip()
    if not target:
        return None

    def _make_word_item(w: dict, score: float = 1.0) -> dict:
        return {
            "text": w["text"],
            "x": int(w["x"]),
            "y": int(w["y"]),
            "w": int(w["w"]),
            "h": int(w["h"]),
            "cx": float(w["cx"]),
            "cy": float(w["cy"]),
            "score": score,
        }

    # 1. Exact word match
    for line in items:
        for w in line.get("words", []):
            if w.get("text", "").strip() == target:
                return _make_word_item(w, score=1.0)

    # 2. Contiguous sub-words sequence forming target
    for line in items:
        words = line.get("words", [])
        n = len(words)
        if n >= 2:
            for k in range(2, n + 1):
                for i in range(n - k + 1):
                    sub = words[i:i + k]
                    joined = "".join(w.get("text", "") for w in sub).strip()
                    if joined == target:
                        x1 = min(w["x"] for w in sub)
                        y1 = min(w["y"] for w in sub)
                        x2 = max(w["x"] + w["w"] for w in sub)
                        y2 = max(w["y"] + w["h"] for w in sub)
                        return {
                            "text": joined,
                            "x": int(x1),
                            "y": int(y1),
                            "w": int(x2 - x1),
                            "h": int(y2 - y1),
                            "cx": float((x1 + x2) / 2.0),
                            "cy": float((y1 + y2) / 2.0),
                            "score": 1.0,
                        }

    # 3. Exact full line match
    for line in items:
        if line.get("text", "").strip() == target:
            return dict(line)

    if exact:
        return None

    # 4. Substring in individual word
    for line in items:
        for w in line.get("words", []):
            wt = w.get("text", "")
            if target in wt:
                idx = wt.find(target)
                r1 = idx / len(wt)
                r2 = (idx + len(target)) / len(wt)
                sub_x1 = w["x"] + w["w"] * r1
                sub_x2 = w["x"] + w["w"] * r2
                return {
                    "text": target,
                    "x": int(round(sub_x1)),
                    "y": int(w["y"]),
                    "w": int(round(sub_x2 - sub_x1)),
                    "h": int(w["h"]),
                    "cx": float((sub_x1 + sub_x2) / 2.0),
                    "cy": float(w["cy"]),
                    "score": 0.95,
                }

    # 5. Substring in line with words
    for line in items:
        lt = line.get("text", "")
        if target in lt:
            words = line.get("words", [])
            if words:
                matched_words = [w for w in words if any(c in w.get("text", "") for c in target)]
                if matched_words:
                    x1 = min(w["x"] for w in matched_words)
                    y1 = min(w["y"] for w in matched_words)
                    x2 = max(w["x"] + w["w"] for w in matched_words)
                    y2 = max(w["y"] + w["h"] for w in matched_words)
                    return {
                        "text": target,
                        "x": int(x1),
                        "y": int(y1),
                        "w": int(x2 - x1),
                        "h": int(y2 - y1),
                        "cx": float((x1 + x2) / 2.0),
                        "cy": float((y1 + y2) / 2.0),
                        "score": 0.90,
                    }
            # Fallback interpolation for line without words (e.g. RapidOCR)
            idx = lt.find(target)
            r1 = idx / len(lt)
            r2 = (idx + len(target)) / len(lt)
            sub_x1 = line["x"] + line["w"] * r1
            sub_x2 = line["x"] + line["w"] * r2
            return {
                "text": target,
                "x": int(round(sub_x1)),
                "y": int(line["y"]),
                "w": int(round(sub_x2 - sub_x1)),
                "h": int(line["h"]),
                "cx": float((sub_x1 + sub_x2) / 2.0),
                "cy": float(line["cy"]),
                "score": 0.85,
            }

    # 6. Case-insensitive / fuzzy match
    target_lower = target.lower()
    for line in items:
        if target_lower in line.get("text", "").lower():
            return dict(line)

    return None


def _find(items: list[dict], text: str) -> list[dict]:
    """Find OCR items whose text matches (exact or contains)."""
    elem = match_text_element(items, text, exact=False)
    if elem:
        return [elem]
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
    """Click a button/element by its visible text using hierarchical sniffing."""
    import pyautogui
    from .vision_locator import locate_text_on_screen

    elem = locate_text_on_screen(text, use_hierarchical=True)
    if not elem:
        items = _ocr_full_screen()
        cands = [it["text"] for it in items if len(it["text"]) <= len(text) + 4]
        hint = f" 相近文字: {cands[:8]}" if cands else ""
        return f"[error] 屏幕上没找到 '{text}'{hint}"

    cx, cy = int(round(elem["cx"])), int(round(elem["cy"]))
    pyautogui.moveTo(cx, cy, duration=0.0)
    for _ in range(max(1, click_count)):
        pyautogui.click()
        time.sleep(0.02)
    tier_info = f" (第{elem.get('tier', 3)}级命中)" if "tier" in elem else ""
    return f"[ok] 已点击 '{elem['text']}' 位置 ({cx},{cy}){tier_info}"


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
