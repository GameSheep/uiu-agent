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
    open_or_focus_app,
)
from .wechat_tools import SEND_WECHAT_DEF, send_wechat

DESKTOP_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "app_open_or_focus",
            "description": "打开任何软件：已启动的自动弹到最前面置顶激活，未启动的自动智能查找并启动然后置顶（支持别名如'微信','Chrome','记事本','Outlook','VSCode'等）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "软件名称、别名或路径，例如 '微信', 'chrome', 'notepad', 'outlook'"}
                },
                "required": ["app_name"],
            },
        },
    },
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
    },
    {
        "type": "function",
        "function": {
            "name": "gui_action_pipeline",
            "description": "极速免思考连续执行 GUI 复合动作流（每步控制在 0.5 秒内，规避多轮 LLM 思考与网络往返）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "动作步骤列表，支持 action: 'app', 'hotkey', 'click_at', 'click_offset', 'click_text', 'type', 'key', 'scroll', 'wait', 'read_text'"
                    }
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_chatgpt_quota",
            "description": "一键直达免思考查询 ChatGPT 客户端剩余额度与使用限制（全流程 1.5 秒内直接返回结果）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scroll_for_more": {"type": "boolean", "description": "是否向下滚动获取更多模型限额详情", "default": False}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cc_switch_provider_remark",
            "description": "一键秒级免思考修改 CC Switch 中指定供应商的备注信息（带窗口恢复、悬浮交互与底层数据库核验）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_name": {"type": "string", "description": "供应商名称，如 'Zhipu GLM'"},
                    "new_remark": {"type": "string", "description": "新的备注文本内容"},
                },
                "required": ["provider_name", "new_remark"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screen_icon_find",
            "description": "定位屏幕上的纯图形图标（如铅笔、齿轮设置、删除、复制等无文字按钮），支持模板匹配与文字锚点相对推导。",
            "parameters": {
                "type": "object",
                "properties": {
                    "icon_name": {"type": "string", "description": "标准图标名（如 'pencil', 'edit', 'gear', 'settings', 'trash', 'delete', 'copy', 'close', 'search', 'refresh', 'plus'）", "default": ""},
                    "anchor_text": {"type": "string", "description": "参考锚点文字（如 'Zhipu GLM'），用于在文字附近找图标", "default": ""},
                    "direction": {"type": "string", "enum": ["right", "left", "below", "above"], "description": "相对锚点的方向（默认 right）", "default": "right"},
                    "index": {"type": "integer", "description": "相对方向上的第几个图标（1-based，默认 1）", "default": 1},
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "限定搜索区域 [x, y, w, h]"
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ui_control_find",
            "description": "通过 Windows UIA 辅助功能树直接探测无文本控件（基于 aria-label、Name、AutomationId 等无障碍属性，<1ms 零视觉开销）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "控件名称或 aria-label（如 '编辑', '保存', '关闭'）"},
                    "control_type": {"type": "string", "description": "控件类型（如 'Button', 'Edit', 'CheckBox'，默认 'Button'）", "default": "Button"},
                    "window_title": {"type": "string", "description": "限定搜索的目标窗口标题关键字", "default": ""},
                    "automation_id": {"type": "string", "description": "控件 AutomationId", "default": ""}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "smart_interact",
            "description": "统一多模态自愈交互原语：自动执行 UIA -> OCR -> 锚点图标 -> 模板匹配 四级降级重试，并核验点击前后屏幕视觉变化，杜绝静默失败。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "目标标识，支持控件名、文字或图标名（如 '保存', '设置', 'pencil', 'close'）",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["click", "double_click", "right_click", "hover", "find_only"],
                        "description": "动作类型（默认 click）",
                        "default": "click",
                    },
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "限定搜索区域 [x, y, w, h]",
                    },
                    "verify_change": {
                        "type": "boolean",
                        "description": "是否核验操作前后屏幕视觉差分（默认 true）",
                        "default": True,
                    },
                    "window_title": {
                        "type": "string",
                        "description": "可选限定的窗口标题",
                        "default": "",
                    },
                },
                "required": ["target"],
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

        elif name == "app_open_or_focus":
            return open_or_focus_app(args.get("app_name", ""))

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
            elem = locate_text_on_screen(target, use_hierarchical=True)
            if elem:
                return json.dumps({
                    "found": True,
                    "text": elem.get("text"),
                    "x": int(round(elem["cx"])),
                    "y": int(round(elem["cy"])),
                    "tier": elem.get("tier", 3),
                }, ensure_ascii=False)
            if scroll:
                import win32api
                sw = win32api.GetSystemMetrics(0)
                sh = win32api.GetSystemMetrics(1)
                elem = scroll_and_find(target, scroll_zone=(0, 0, sw, sh), max_scrolls=3)
                if elem:
                    return json.dumps({
                        "found": True,
                        "text": elem.get("text"),
                        "x": int(round(elem["cx"])),
                        "y": int(round(elem["cy"])),
                        "note": "翻页后找到",
                    }, ensure_ascii=False)
            return json.dumps({"found": False, "message": f"未在屏幕上找到 '{target}'"}, ensure_ascii=False)

        elif name == "mouse_click_at":
            return mouse_click(
                x=int(round(args["x"])),
                y=int(round(args["y"])),
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

        elif name == "gui_action_pipeline":
            from .fast_pipeline import gui_action_pipeline
            return gui_action_pipeline(args.get("steps", []))

        elif name == "check_chatgpt_quota":
            from .fast_pipeline import check_chatgpt_quota
            return check_chatgpt_quota(scroll_for_more=args.get("scroll_for_more", False))

        elif name == "update_cc_switch_provider_remark":
            from .fast_pipeline import update_cc_switch_provider_remark
            return update_cc_switch_provider_remark(
                provider_name=args.get("provider_name", ""),
                new_remark=args.get("new_remark", ""),
            )

        elif name == "screen_icon_find":
            from .icon_locator import match_icon_template, find_icons_relative_to_anchor, detect_icon_regions
            icon_name = args.get("icon_name", "").strip()
            anchor_text = args.get("anchor_text", "").strip()
            direction = args.get("direction", "right")
            index = int(args.get("index", 1))
            reg = args.get("region")
            reg_tuple = tuple(reg) if reg and len(reg) == 4 else None

            res = None
            if anchor_text:
                res = find_icons_relative_to_anchor(anchor_text, direction=direction, index=index, region=reg_tuple)
            elif icon_name:
                res = match_icon_template(icon_name, region=reg_tuple)
            else:
                boxes = detect_icon_regions(reg_tuple)
                if boxes:
                    return json.dumps({"found": True, "count": len(boxes), "icons": boxes[:10]}, ensure_ascii=False)

            if res:
                return json.dumps({"found": True, "x": int(round(res["cx"])), "y": int(round(res["cy"])), "detail": res}, ensure_ascii=False)
            return json.dumps({"found": False, "message": f"未找到图标 (icon={icon_name}, anchor={anchor_text})"}, ensure_ascii=False)

        elif name == "ui_control_find":
            from .uia_locator import find_uia_control
            res = find_uia_control(
                name=args.get("name"),
                control_type=args.get("control_type", "Button"),
                window_title=args.get("window_title"),
                automation_id=args.get("automation_id"),
            )
            if res:
                return json.dumps({"found": True, "x": res["cx"], "y": res["cy"], "detail": res}, ensure_ascii=False)
            return json.dumps({"found": False, "message": f"未找到 UIA 控件: {args}"}, ensure_ascii=False)

        elif name == "smart_interact":
            from .smart_interact import smart_interact
            res = smart_interact(
                target=args.get("target"),
                action=args.get("action", "click"),
                region=args.get("region"),
                verify_change=args.get("verify_change", True),
                window_title=args.get("window_title"),
            )
            return json.dumps(res, ensure_ascii=False)

        else:
            return f"[error] 未知工具: {name}"

    except Exception as e:
        return f"[error] 执行工具 {name} 异常: {type(e).__name__}: {e}"