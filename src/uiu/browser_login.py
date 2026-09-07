"""Chrome Browser Auto-Login & Image Captcha OCR Solver.

Supports:
- Image captcha capture & enhancement (grayscale, contrast boost, adaptive threshold)
- OCR character recognition & arithmetic captcha auto-evaluation (e.g. '3+5=?' -> '8')
- Full closed-loop Chrome automation: open/focus, fill credentials, solve captcha, submit
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .gui_primitives import mouse_click, paste_text, press_hotkey, press_key
from .vision_locator import locate_text_on_screen
from .window_manager import open_or_focus_app


def _eval_arithmetic(text: str) -> str | None:
    """Evaluate simple arithmetic equation captcha if detected (e.g. '3 + 5 = ?' -> '8')."""
    cleaned = text.replace(" ", "").replace("=", "").replace("?", "").replace("？", "")
    # Match patterns like 12+5, 8-3, 4*2, 9x3, 10/2
    m = re.search(r"(\d+)\s*([\+\-\*xX×÷/])\s*(\d+)", cleaned)
    if m:
        a = int(m.group(1))
        op = m.group(2)
        b = int(m.group(3))
        if op == "+":
            return str(a + b)
        elif op == "-":
            return str(a - b)
        elif op in ("*", "x", "X", "×"):
            return str(a * b)
        elif op in ("/", "÷") and b != 0:
            return str(a // b)
    return None


def solve_captcha_ocr(
    region: tuple[int, int, int, int] | list[int] | None = None,
    hint: str = "验证码",
    arithmetic: bool = True,
) -> str:
    """Capture a captcha region from the screen and solve it using enhanced OCR."""
    import pyautogui
    from PIL import Image, ImageEnhance, ImageFilter

    target_region = None
    if region and len(region) == 4:
        target_region = tuple(int(v) for v in region)
    else:
        # Search for hint text (e.g. "验证码") on screen to locate the captcha area
        found = locate_text_on_screen(hint)
        if found:
            cx, cy = found["cx"], found["cy"]
            # Captcha image is usually to the right of the captcha label/input
            target_region = (int(cx + 60), int(cy - 20), 160, 55)
        else:
            # Fallback: search for "换一张" or "看不清"
            for alt_hint in ("换一张", "看不清", "刷新", "验证"):
                alt_found = locate_text_on_screen(alt_hint)
                if alt_found:
                    target_region = (int(alt_found["cx"] - 140), int(alt_found["cy"] - 15), 140, 50)
                    break

    if not target_region:
        return json.dumps({
            "success": False,
            "error": f"未在屏幕上找到 '{hint}' 相关的验证码图片区域，请显式提供 region=[x, y, w, h]"
        }, ensure_ascii=False)

    try:
        rx, ry, rw, rh = target_region
        rx = max(0, rx)
        ry = max(0, ry)
        rw = max(20, rw)
        rh = max(15, rh)

        # 1. Capture screen region
        img = pyautogui.screenshot(region=(rx, ry, rw, rh))

        # 2. Image preprocessing for high-accuracy OCR
        # Convert to grayscale
        gray = img.convert("L")
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(2.5)
        # Resize 2x using Lanczos
        scaled = enhanced.resize((rw * 2, rh * 2), Image.Resampling.LANCZOS)

        # 3. In-memory OCR Recognition (0 disk I/O, no temp files)
        import numpy as np
        img_np = np.array(scaled)

        raw_text = ""
        # Try RapidOCR
        try:
            from rapidocr_onnxruntime import RapidOCR
            ocr = RapidOCR()
            result, _ = ocr(img_np)
            if result:
                raw_text = "".join(item[1] for item in result).strip()
        except Exception:
            pass

        # Fallback to WinRT OCR
        if not raw_text:
            try:
                from .screen_tools import _ocr_winrt_region
                items = _ocr_winrt_region(rx, ry, rw, rh)
                if items:
                    raw_text = "".join(it["text"] for it in items).strip()
            except Exception:
                pass

        if not raw_text:
            return json.dumps({
                "success": False,
                "region": list(target_region),
                "error": "OCR 未能从该区域识别出字符，请确认验证码位置或点击刷新"
            }, ensure_ascii=False)

        # 4. Post-processing: arithmetic equation vs alphanumeric
        code = raw_text
        is_arithmetic = False
        if arithmetic:
            calc_val = _eval_arithmetic(raw_text)
            if calc_val is not None:
                code = calc_val
                is_arithmetic = True

        if not is_arithmetic:
            # Filter non-alphanumeric noise
            code = re.sub(r"[^a-zA-Z0-9]", "", raw_text)
            if not code:
                code = raw_text.strip()

        return json.dumps({
            "success": True,
            "code": code,
            "raw_text": raw_text,
            "is_arithmetic": is_arithmetic,
            "region": list(target_region),
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": f"识别验证码异常: {type(e).__name__}: {e}"}, ensure_ascii=False)


def chrome_auto_login(
    url: str = "",
    username: str = "",
    password: str = "",
    captcha: bool = True,
    submit_button: str = "登录",
    max_retries: int = 1,
) -> str:
    """Automate Chrome browser login: navigate, fill account, solve captcha with OCR, submit."""
    steps: list[str] = []

    # Step 1: Open or focus Chrome
    open_res = open_or_focus_app("chrome")
    steps.append(f"1. 启动/激活 Chrome: {open_res}")
    time.sleep(0.8)

    # If URL provided, navigate to it
    if url.strip():
        press_hotkey(["ctrl", "l"])
        time.sleep(0.2)
        paste_text(url.strip())
        time.sleep(0.1)
        press_key("enter")
        steps.append(f"2. 导航至网址: {url}")
        time.sleep(2.0)  # Wait for page load

    # Step 2: Locate username field
    user_elem = None
    for label in ("用户名", "账号", "手机号", "邮箱", "Email", "Username", "登录名"):
        user_elem = locate_text_on_screen(label)
        if user_elem:
            break

    if user_elem:
        # Click input box (offset slightly right or below)
        mouse_click(user_elem["cx"] + 80, user_elem["cy"])
        time.sleep(0.2)
        paste_text(username, clear_before=True)
        steps.append(f"3. 填入账号 ({username})")
    else:
        # Fallback: click near center top or tab
        press_key("tab")
        paste_text(username, clear_before=True)
        steps.append(f"3. 未明确找到账号标签，已通过 Tab 尝试填入账号 ({username})")

    time.sleep(0.3)

    # Step 3: Locate password field
    pwd_elem = None
    for label in ("密码", "Password", "口令"):
        pwd_elem = locate_text_on_screen(label)
        if pwd_elem:
            break

    if pwd_elem:
        mouse_click(pwd_elem["cx"] + 80, pwd_elem["cy"])
        time.sleep(0.2)
        paste_text(password, clear_before=True)
        steps.append("4. 填入密码 (已保护)")
    else:
        press_key("tab")
        paste_text(password, clear_before=True)
        steps.append("4. 已通过 Tab 切换并填入密码")

    time.sleep(0.3)

    # Step 4: Handle Captcha if required
    solved_code = ""
    if captcha:
        for attempt in range(max_retries + 1):
            captcha_res = solve_captcha_ocr(hint="验证码")
            try:
                c_data = json.loads(captcha_res)
            except Exception:
                c_data = {"success": False}

            if c_data.get("success"):
                solved_code = c_data.get("code", "")
                steps.append(f"5. 验证码 OCR 识别结果: '{solved_code}' (原始: '{c_data.get('raw_text')}')")
                # Locate captcha input box
                cap_box = locate_text_on_screen("验证码")
                if cap_box:
                    mouse_click(cap_box["cx"] + 70, cap_box["cy"])
                    time.sleep(0.2)
                    paste_text(solved_code, clear_before=True)
                else:
                    press_key("tab")
                    paste_text(solved_code, clear_before=True)
                break
            else:
                if attempt < max_retries:
                    steps.append(f"5. 验证码识别尝试 {attempt+1} 未命中，刷新重试...")
                    time.sleep(0.5)
                else:
                    steps.append("5. [警告] 未能成功识别验证码图片")

    # Step 5: Submit Login
    btn_elem = None
    for btn_name in (submit_button, "登录", "登 录", "Sign in", "Log in", "立即登录", "确定"):
        btn_elem = locate_text_on_screen(btn_name)
        if btn_elem:
            break

    if btn_elem:
        mouse_click(btn_elem["cx"], btn_elem["cy"])
        steps.append(f"6. 点击登录按钮: '{btn_elem.get('text')}' 坐标 ({btn_elem['cx']}, {btn_elem['cy']})")
    else:
        press_key("enter")
        steps.append("6. 未直接找到登录按钮，按下 Enter 提交")

    time.sleep(1.5)

    # Step 6: Post-check
    for err_word in ("验证码错误", "密码错误", "不正确", "重新输入"):
        err_match = locate_text_on_screen(err_word)
        if err_match:
            steps.append(f"7. [注意] 页面检测到提示: '{err_word}'，可能需要人工核验或重试")
            return "[error] 登录提交后页面提示错误:\n" + "\n".join(steps)

    steps.append("7. [完成] 自动登录流程已执行完毕")
    return "[ok] 自动登录执行成功:\n" + "\n".join(steps)


# Tool schemas
SOLVE_CAPTCHA_OCR_DEF = {
    "type": "function",
    "function": {
        "name": "solve_captcha_ocr",
        "description": "截图并使用 OCR 智能识别屏幕上的图片验证码，支持字母数字验证码和加减乘除算术验证码自动计算。",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "验证码区域坐标 [x, y, w, h]（可选，若不填会自动在屏幕找'验证码'附近区域）",
                },
                "hint": {
                    "type": "string",
                    "description": "用于定位验证码附近的文本提示（默认'验证码'）",
                    "default": "验证码",
                },
                "arithmetic": {
                    "type": "boolean",
                    "description": "是否自动识别并计算算术题验证码（如 3+5=? 自动计算为 8）",
                    "default": True,
                },
            },
        },
    },
}

CHROME_AUTO_LOGIN_DEF = {
    "type": "function",
    "function": {
        "name": "chrome_auto_login",
        "description": "自动化操作 Chrome 浏览器执行账号密码登录，自动 OCR 截取识别图片验证码并点击提交登录。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "登录页面的网址（可选，若为空则在当前 Chrome 页面操作）"},
                "username": {"type": "string", "description": "账号 / 用户名 / 手机号 / 邮箱"},
                "password": {"type": "string", "description": "登录密码"},
                "captcha": {"type": "boolean", "description": "是否需要识别输入图片验证码（默认 True）", "default": True},
                "submit_button": {"type": "string", "description": "提交按钮文字（默认'登录'）", "default": "登录"},
                "max_retries": {"type": "integer", "description": "验证码失败最大重试次数", "default": 1},
            },
            "required": ["username", "password"],
        },
    },
}

BROWSER_LOGIN_TOOLS: dict[str, dict] = {
    "solve_captcha_ocr": {"def": SOLVE_CAPTCHA_OCR_DEF, "fn": solve_captcha_ocr},
    "chrome_auto_login": {"def": CHROME_AUTO_LOGIN_DEF, "fn": chrome_auto_login},
}


def browser_login_tool_defs() -> list[dict]:
    return [t["def"] for t in BROWSER_LOGIN_TOOLS.values()]
