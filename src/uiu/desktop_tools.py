"""Universal Desktop Agent Tool Dispatcher & Registration."""

from __future__ import annotations

import json
from typing import Any

from .gui_primitives import (
    mouse_click,
    mouse_drag,
    mouse_scroll,
    paste_text,
    press_hotkey,
    press_key,
)
from .vision_locator import (
    locate_text_on_screen,
    scroll_and_find,
)
from .window_manager import (
    find_window,
    focus_window,
    launch_application,
    list_visible_windows,
)
from .wechat_tools import SEND_WECHAT_DEF, send_wechat

DESKTOP_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "window_list",
            "description": "列出当前桌面所有打开的窗口（获取标题、位置等）。操作软件前建议先确认软件是否已打开。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_focus",
            "description": "置顶并激活指定软件窗口。任何软件操作前必须先置顶。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title_keyword": {"type": "string", "description": "窗口标题包含的关键字，如 '微信', 'Chrome'"}
                },
                "required": ["title_keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_launch",
            "description": "启动程序或打开文件/URL。如果窗口未运行，使用此工具启动它。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "系统命令（如 'notepad'）或 exe 路径、文件路径"}
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_ocr_find",
            "description": "OCR 屏幕找字，返回目标文字在屏幕上的绝对物理中心坐标 (x, y)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_text": {"type": "string", "description": "要在屏幕上找的文字/按钮名"},
                    "scroll_if_missing": {"type": "boolean", "description": "若未找到是否滚轮翻页继续寻找", "default": False}
                },
                "required": ["target_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click_at",
            "description": "点击屏幕上的物理绝对坐标。配合 screen_ocr_find 找到的坐标使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "clicks": {"type": "integer", "enum": [1, 2], "default": 1}
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "text_paste",
            "description": "通过剪贴板安全写入文本（防输入法拼音打偏）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待输入文本"},
                    "clear_before": {"type": "boolean", "description": "是否全选清空后输入", "default": False}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_shortcut",
            "description": "按下单键或组合键（如确认用 ['enter']，快捷键用 ['ctrl', 'c']）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "按键列表"}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_scroll_at",
            "description": "在指定位置滚动鼠标滚轮翻页。",
            "parameters": {
                "type": "object",
                "properties": {
                    "clicks": {"type": "integer", "description": "负数向下滚动，正数向上滚动"},
                    "x": {"type": "integer", "description": "X 坐标"},
                    "y": {"type": "integer", "description": "Y 坐标"}
                },
                "required": ["clicks"],
            },
        },
    }
]

# 将微信专用工具与通用工具整合
ALL_TOOLS = DESKTOP_TOOL_SCHEMAS + [SEND_WECHAT_DEF]


def get_all_tool_schemas() -> list[dict[str, Any]]:
    """供主程序传入大模型的 tools 参数"""
    return ALL_TOOLS


def dispatch_tool(name: str, args: dict[str, Any]) -> str:
    """Agent 执行工具调用的唯一统一分发入口"""
    try:
        if name == "send_wechat":
            return send_wechat(**args)

        elif name == "window_list":
            wins = list_visible_windows()
            simplified = [
                {"title": w["title"], "rect": w["rect"], "minimized": w["is_minimized"]}
                for w in wins[:15]
            ]
            return json.dumps(simplified, ensure_ascii=False)

        elif name == "window_focus":
            title = args.get("title_keyword", "")
            win = find_window(title)
            if not win:
                return f"[error] 未找到标题包含 '{title}' 的窗口"
            return focus_window(win["hwnd"])

        elif name == "app_launch":
            return launch_application(args.get("target", ""))

        elif name == "screen_ocr_find":
            target = args.get("target_text", "")
            scroll = args.get("scroll_if_missing", False)
            elem = locate_text_on_screen(target)
            if elem:
                return json.dumps({"found": True, "text": elem.get("text"), "x": elem["cx"], "y": elem["cy"]}, ensure_ascii=False)
            if scroll:
                import win32api
                sw = win32api.GetSystemMetrics(0)
                sh = win32api.GetSystemMetrics(1)
                elem = scroll_and_find(target, scroll_zone=(0, 0, sw, sh), max_scrolls=3)
                if elem:
                    return json.dumps({"found": True, "text": elem.get("text"), "x": elem["cx"], "y": elem["cy"], "note": "翻页后找到"}, ensure_ascii=False)
            return json.dumps({"found": False, "message": f"未在屏幕上找到 '{target}'"}, ensure_ascii=False)

        elif name == "mouse_click_at":
            return mouse_click(
                x=args["x"],
                y=args["y"],
                button=args.get("button", "left"),
                clicks=args.get("clicks", 1),
            )

        elif name == "text_paste":
            return paste_text(text=args["text"], clear_before=args.get("clear_before", False))

        elif name == "keyboard_shortcut":
            keys = args.get("keys", [])
            if not keys:
                return "[error] 按键列表为空"
            return press_key(keys[0]) if len(keys) == 1 else press_hotkey(keys)

        elif name == "mouse_scroll_at":
            return mouse_scroll(clicks=args["clicks"], x=args.get("x"), y=args.get("y"))

        else:
            return f"[error] 未知工具: {name}"

    except Exception as e:
        return f"[error] 执行工具 {name} 异常: {type(e).__name__}: {e}"