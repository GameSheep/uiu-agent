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
    },
    {
        "type": "function",
        "function": {
            "name": "hierarchical_execute",
            "description": "基于 Microsoft UFO 架构的 HostAgent + AppAgent 双层分级协同调度器：将跨软件复杂长任务自动拆解为应用子任务，自动调度 App 专家执行并汇聚成果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "用户的跨应用复合长目标（例如 '把 CC Switch 备注修改为 123，然后发微信给文件传输助手通知已更新'）",
                    },
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macro_auto_compile",
            "description": "基于自我编程演进范式：将动作步骤序列自动编译为原生高性能 Python 宏代码并注册，实现后续 0 思考毫秒级复用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "宏名称（如 'update_remark_macro'）"},
                    "target_app": {"type": "string", "description": "目标软件（如 'CC Switch'）", "default": ""},
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "动作列表 [{'action': 'click', ...}, ...]",
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "动态形参列表",
                        "default": [],
                    },
                },
                "required": ["name", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "macro_fast_run",
            "description": "从情境经验记忆库中召回或直接运行已编译的原生零延迟宏（全流程 < 1 秒，0 思考）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "macro_name": {"type": "string", "description": "宏名称或语义查询词（如 'update_cc_switch' 或 '修改备注'）"},
                    "kwargs": {"type": "object", "description": "宏执行所需的动态入参键值对", "default": {}},
                },
                "required": ["macro_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resilient_click",
            "description": "极高鲁棒性自愈点击：自动等待界面动画渲染沉降、自动检测并消解意外遮挡弹窗，并在未生效时触发自愈重试。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "目标元素标识（控件名、文本或图标名称）",
                    },
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "限定搜索区域 [x, y, w, h]",
                    },
                    "wait_stable": {
                        "type": "boolean",
                        "description": "是否等待界面渲染稳定（默认 true）",
                        "default": True,
                    },
                    "auto_dismiss_popups": {
                        "type": "boolean",
                        "description": "是否自动消解阻断性弹窗（默认 true）",
                        "default": True,
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_screen_stable",
            "description": "等待屏幕或指定区域画面变动沉降静止（用于等待加载完成或过渡动画结束）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "限定区域 [x, y, w, h]",
                    },
                    "max_wait_ms": {
                        "type": "number",
                        "description": "最大等待时间毫秒（默认 2000ms）",
                        "default": 2000.0,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "display_scaling_info",
            "description": "获取多显示器几何布局、系统/监视器DPI缩放比（100%, 125%, 150%, 200%）与坐标系校准报告。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "coordinate_anti_drift",
            "description": "计算高精度抗漂移安全点击坐标，支持安全内边距、文本框输入优化、物理/逻辑DPI转换与归一化坐标转换。",
            "parameters": {
                "type": "object",
                "properties": {
                    "box": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "元素包围盒 [x, y, w, h]",
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["center", "safe_center", "input_field", "right_action"],
                        "description": "定位策略（默认 safe_center）",
                        "default": "safe_center",
                    },
                    "is_physical": {
                        "type": "boolean",
                        "description": "是否为图像物理像素坐标，若为 true 则根据 DPI 自动转换为逻辑点击坐标",
                        "default": False,
                    },
                },
                "required": ["box"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "autonomous_goal_run",
            "description": "自主多轮任务执行器（类 Claude Code / Hermes 架构）：包含思考(Thought)、行动(Action)、观察(Observation)、反思(Reflection)四元自适应循环，并在完成后自动编译为宏记忆沉淀。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "要完成的自主目标指令"},
                    "max_steps": {"type": "integer", "description": "最大多轮迭代步数（默认 8）", "default": 8},
                },
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_data_pipeline",
            "description": "跨软件多模态剪贴板管道：支持纯文本、富图像(CF_DIB)、结构化表格(TSV/Markdown/CSV)的高速剪贴板读写与解析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["set_text", "get_text", "set_table", "parse_table"],
                        "description": "剪贴板操作模式",
                    },
                    "text": {"type": "string", "description": "要写入的纯文本内容", "default": ""},
                    "table_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "要转换复制的表格数据列表 [{'col1': 'v1'}, ...]",
                        "default": [],
                    },
                    "format": {
                        "type": "string",
                        "enum": ["tsv", "markdown", "csv"],
                        "description": "表格序列化格式（默认 tsv）",
                        "default": "tsv",
                    },
                },
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_layout_tile",
            "description": "智能视口与双屏吸附：将单/双应用窗口自动分屏并排吸附对齐（left/right/top/bottom/center），确保视觉 Agent 能同时观测并协同两个软件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app1": {"type": "string", "description": "第一个目标软件名称或窗口关键字"},
                    "app2": {"type": "string", "description": "第二个目标软件名称（用于双屏并排分屏）", "default": ""},
                    "position": {
                        "type": "string",
                        "enum": ["left", "right", "top", "bottom", "center", "maximize", "tile_horizontal", "tile_vertical"],
                        "description": "布局方位或分屏方向",
                        "default": "left",
                    },
                },
                "required": ["app1"],
            },
        },
    },
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

        elif name == "hierarchical_execute":
            from .hierarchical_agent import hierarchical_execute
            return hierarchical_execute(goal=args.get("goal", ""))

        elif name == "macro_auto_compile":
            from .trajectory_compiler import ActionTrajectory, save_and_register_macro
            traj = ActionTrajectory(
                name=args.get("name", "macro"),
                target_app=args.get("target_app", ""),
                steps=args.get("steps", []),
                parameters=args.get("parameters", []),
            )
            fn_name, path = save_and_register_macro(traj)
            return f"[ok] 宏 '{fn_name}' 已成功编译并注册至 {path}"

        elif name == "macro_fast_run":
            from .trajectory_compiler import run_compiled_macro
            from .episodic_memory import find_matching_macro
            target = args.get("macro_name", "")
            kwargs = args.get("kwargs", {})
            res = run_compiled_macro(target, **kwargs)
            if not res.startswith("[error] 未找到"):
                return res
            ep = find_matching_macro(target)
            if ep and ep.get("macro_name"):
                matched_name = ep["macro_name"]
                return run_compiled_macro(matched_name, **kwargs)
            return res

        elif name == "resilient_click":
            from .auto_recovery import resilient_click
            res = resilient_click(
                target=args.get("target"),
                region=args.get("region"),
                wait_stable=args.get("wait_stable", True),
                auto_dismiss_popups=args.get("auto_dismiss_popups", True),
            )
            return json.dumps(res, ensure_ascii=False)

        elif name == "wait_screen_stable":
            from .auto_recovery import wait_screen_stable
            ok = wait_screen_stable(
                region=args.get("region"),
                max_wait_ms=float(args.get("max_wait_ms", 2000.0)),
            )
            return json.dumps({"stable": ok, "message": "画面已静止" if ok else "等待超时，画面仍有动态变动"}, ensure_ascii=False)

        elif name == "display_scaling_info":
            from .dpi_manager import calibrate_screen_alignment
            info = calibrate_screen_alignment()
            return f"[ok] 显示器与 DPI 缩放诊断: {json.dumps(info, ensure_ascii=False)}"

        elif name == "coordinate_anti_drift":
            from .dpi_manager import calculate_safe_target, physical_to_logical
            box = args.get("box", [0, 0, 10, 10])
            strategy = args.get("strategy", "safe_center")
            is_phys = args.get("is_physical", False)
            tx, ty = calculate_safe_target(box, strategy=strategy)
            if is_phys:
                tx, ty = physical_to_logical(tx, ty)
            return f"[ok] 抗漂移安全坐标计算完成: target=({tx}, {ty}), strategy={strategy}"

        elif name == "autonomous_goal_run":
            from .autonomous_loop import run_autonomous_goal
            return run_autonomous_goal(goal=args.get("goal", ""), max_steps=int(args.get("max_steps", 8)))

        elif name == "clipboard_data_pipeline":
            from .data_pipeline import clipboard_get_text, clipboard_set_text, clipboard_set_table, clipboard_parse_table
            mode = args.get("mode", "get_text")
            if mode == "set_text":
                return clipboard_set_text(args.get("text", ""))
            elif mode == "get_text":
                txt = clipboard_get_text()
                return f"[ok] 剪贴板文本内容 ({len(txt)} 字符): {txt[:300]}"
            elif mode == "set_table":
                return clipboard_set_table(args.get("table_data", []), format_type=args.get("format", "tsv"))
            elif mode == "parse_table":
                records = clipboard_parse_table(args.get("text"))
                return f"[ok] 解析剪贴板表格结构成功 ({len(records)} 行): {json.dumps(records, ensure_ascii=False)}"
            else:
                return f"[error] 未知模式: {mode}"

        elif name == "window_layout_tile":
            from .layout_manager import snap_window, tile_windows
            app1 = args.get("app1", "")
            app2 = args.get("app2", "")
            pos = args.get("position", "left")
            if app2 or pos in ("tile_horizontal", "tile_vertical"):
                direction = "vertical" if pos == "tile_vertical" else "horizontal"
                res_tile = tile_windows(app1, app2, direction=direction)
                return json.dumps(res_tile, ensure_ascii=False)
            else:
                return snap_window(app1, position=pos)

        else:
            return f"[error] 未知工具: {name}"




    except Exception as e:
        return f"[error] 执行工具 {name} 异常: {type(e).__name__}: {e}"