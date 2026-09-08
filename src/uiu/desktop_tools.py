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
    {
        "type": "function",
        "function": {
            "name": "visual_tag_screen",
            "description": "生成 Set-of-Mark 视口交互标记：为当前屏幕或区域内所有可交互控件与文本打上高对比度编号标签（[1], [2], [3]...），杜绝视觉模型坐标幻觉。",
            "parameters": {
                "type": "object",
                "properties": {
                    "region": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "限定视口区域 [x, y, w, h]",
                    },
                    "window_title": {"type": "string", "description": "限定窗口标题", "default": ""},
                    "max_elements": {"type": "integer", "description": "最大标记元素数（默认 40）", "default": 40},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "som_click_tag",
            "description": "通过 Set-of-Mark 编号标签直接交互：指定编号（如 1 或 '1'）直接执行自愈点击，杜绝误触与坐标偏移。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "目标元素编号（如 '1', '5'）"},
                    "action": {
                        "type": "string",
                        "enum": ["click", "double_click", "right_click", "hover"],
                        "description": "动作类型（默认 click）",
                        "default": "click",
                    },
                    "verify_change": {
                        "type": "boolean",
                        "description": "是否核验点击视觉变动（默认 true）",
                        "default": True,
                    },
                },
                "required": ["tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_health_check",
            "description": "检测指定应用窗口是否处于未响应/假死状态（IsHungAppWindow），并返回 CPU、内存与健康诊断报告。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标软件窗口标题或进程名"},
                    "auto_revive": {
                        "type": "boolean",
                        "description": "若处于假死未响应状态，是否自动尝试唤醒或安全重启（默认 false）",
                        "default": False,
                    },
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spatial_anchor_find",
            "description": "相对空间拓扑定位：基于锚点元素查找相对方位的目标控件（支持 'right', 'left', 'below', 'above', 'inside'）。例如：点击‘智谱 GLM’右侧的‘编辑’。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标元素名称/类型（如 '编辑', '输入框', '保存'）"},
                    "anchor": {"type": "string", "description": "参考锚点元素名称（如 '智谱 GLM', '用户名'）"},
                    "relation": {
                        "type": "string",
                        "enum": ["right", "left", "below", "above", "inside"],
                        "description": "相对空间方位（默认 right）",
                        "default": "right",
                    },
                    "max_distance": {
                        "type": "number",
                        "description": "最大允许搜索间距像素（默认 400.0）",
                        "default": 400.0,
                    },
                },
                "required": ["target", "anchor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_probe_find",
            "description": "虚拟滚动探针：自动沿长页面/长列表滚动查找指定目标，通过画面差分自动探测滚动边界防止死循环。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "要搜索的目标文字或控件名"},
                    "anchor": {"type": "string", "description": "可选相对锚点", "default": ""},
                    "max_scrolls": {"type": "integer", "description": "最大滚动次数（默认 6）", "default": 6},
                    "scroll_clicks": {"type": "integer", "description": "单次滚动单位（负数向下，默认 -4）", "default": -4},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task_checkpoint_manage",
            "description": "长任务检查点与 WAL 事务管理：查看未完成任务列表、断点续跑、或执行事务回滚。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list_incomplete", "rollback"],
                        "description": "操作动作",
                    },
                    "task_id": {"type": "string", "description": "目标任务 ID（回滚时必填）", "default": ""},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_cdp_action",
            "description": "浏览器 CDP 混合自动化：若 Chrome/Edge 开启了调试端口 9222，直接执行 DOM CSS 点击、读取 innerText 或运行 JS。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["status", "get_text", "click_selector"],
                        "description": "CDP 动作",
                    },
                    "selector": {"type": "string", "description": "CSS 选择器（点击时必填）", "default": ""},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_default_attach",
            "description": "接管用户日常 Chrome/Edge/Brave 浏览器：免登录、保留全部 Cookie 与已打开标签页，通过 CDP 调试端点附着至当前活动页面。",
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "description": "CDP 调试端口（默认 9222）", "default": 9222},
                    "browser": {
                        "type": "string",
                        "enum": ["auto", "chrome", "edge", "brave"],
                        "description": "目标浏览器类型：'auto' 自动读取 Windows 系统默认浏览器，亦可显式指定 'chrome' 或 'edge'",
                        "default": "auto"
                    },
                    "auto_restart": {"type": "boolean", "description": "若浏览器运行中但未开启调试端口，是否允许平滑重挂载（带 --restore-last-session）", "default": False}
                }
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_tabs_manage",
            "description": "管理已接管浏览器的标签页：列出所有标签页(list)、去重打开或激活网址(open)、切换到指定标题/网址的标签页(switch)、或关闭标签页(close)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "open", "switch", "close"],
                        "description": "操作类型：list 列出所有Tab, open 打开或去重唤醒URL, switch 切换Tab, close 关闭Tab",
                        "default": "list"
                    },
                    "target": {
                        "type": "string",
                        "description": "标签页序号（从0开始）或标题/网址包含的关键字（用于 switch 和 close）",
                        "default": ""
                    },
                    "url": {
                        "type": "string",
                        "description": "要打开或激活的网址（用于 open）",
                        "default": ""
                    }
                },
                "required": ["action"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_content_extract",
            "description": "从已接管浏览器当前页面中高精度提取内容（支持 markdown 结构化正文、table 结构化表格、text 纯文本、html 节点代码），告别 OCR 模糊与换行错位。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["markdown", "table", "text", "html"],
                        "description": "提取模式：markdown 提取结构化正文与标题列表, table 提取结构化表格数据, text 纯文本, html 元素代码",
                        "default": "markdown"
                    },
                    "selector": {
                        "type": "string",
                        "description": "可选 CSS 选择器限定提取区域（如 'article', '.main', 'table', '#content'）",
                        "default": ""
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最大截断字符数（默认 4000）",
                        "default": 4000
                    }
                }
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_eval_js",
            "description": "在已接管浏览器的活动页面上下文安全执行自定义 JavaScript 脚本并返回序列化结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "要执行的 JavaScript 表达式或自执行函数代码，如 'document.title' 或 '(() => ({ count: document.querySelectorAll(\"a\").length }))()'"
                    }
                },
                "required": ["script"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_list_installed",
            "description": "扫描当前系统上已安装的全部现代浏览器（Chrome, Edge, Brave等），返回可执行路径、配置目录、默认浏览器标识及当前运行状态。",
            "parameters": {
                "type": "object",
                "properties": {}
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_explore_step",
            "description": "在已接管的默认浏览器中执行探索性交互步进：支持 'inspect' 获取当前页可交互元素树；或执行 'click', 'fill', 'press', 'hover', 'scroll', 'navigate' 并自动提取复合指纹与效应核验。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["inspect", "click", "fill", "press", "hover", "scroll", "navigate", "wait"],
                        "description": "交互动作（'inspect' 仅获取当前页面元素，其他为执行操作）",
                        "default": "inspect"
                    },
                    "target": {
                        "type": "string",
                        "description": "目标元素标识：可以是元素序号（如 '1' 或 1）、文本内容（如 '百度一下'）、CSS 选择器或 TestID",
                        "default": ""
                    },
                    "value": {
                        "type": "string",
                        "description": "输入内容（fill/type 时为输入文字，press 时为按键如 'Enter'，navigate 时为 URL）",
                        "default": ""
                    }
                }
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_compile_macro",
            "description": "将探索成功的浏览器动作序列自动编译为独立、零延迟、带视觉自愈热修补能力的 Python Playwright 宏脚本并注册。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "宏名称（如 'search_baidu_macro'）"},
                    "description": {"type": "string", "description": "宏功能描述", "default": ""},
                    "start_url": {"type": "string", "description": "起始目标网址", "default": ""},
                    "steps": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "动作列表 [{'action': 'fill', 'target': 'kw', 'value': 'keyword', 'fingerprint': {...}}, ...]"
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "动态入参形参列表（例如 ['keyword']）",
                        "default": []
                    }
                },
                "required": ["name", "steps"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_macro_run",
            "description": "零延迟直接运行已编译的 Playwright 浏览器宏（支持传入动态参数，如 keyword='Python'），内置前端改版视觉自愈与原地热修补。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "已编译宏的名称（如 'search_baidu_macro'）"},
                    "kwargs": {"type": "object", "description": "传递给宏的动态参数键值对", "default": {}}
                },
                "required": ["name"]
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
    from .desktop_guard import check_desktop_action_allowed
    allowed, reason = check_desktop_action_allowed(name)
    if not allowed:
        return f"[error] {reason}"

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

        elif name == "visual_tag_screen":
            from .som_tagger import capture_and_tag_screen
            return capture_and_tag_screen(
                region=args.get("region"),
                window_title=args.get("window_title"),
                max_elements=int(args.get("max_elements", 40)),
            )

        elif name == "som_click_tag":
            from .som_tagger import click_som_tag
            return click_som_tag(
                tag_id=args.get("tag", ""),
                action=args.get("action", "click"),
                verify_change=args.get("verify_change", True),
            )

        elif name == "process_health_check":
            from .process_watchdog import check_app_health, revive_or_restart_app
            target = args.get("target", "")
            auto_revive = args.get("auto_revive", False)
            if auto_revive:
                return revive_or_restart_app(target)
            else:
                info = check_app_health(target)
                return f"[ok] 应用健康检查报告: {json.dumps(info, ensure_ascii=False)}"

        elif name == "spatial_anchor_find":
            from .spatial_locator import find_element_by_relation
            elem = find_element_by_relation(
                target=args.get("target", ""),
                anchor=args.get("anchor", ""),
                relation=args.get("relation", "right"),
                max_distance_px=float(args.get("max_distance", 400.0)),
            )
            if elem:
                return f"[ok] 相对空间定位成功: 找到目标 '{elem['text']}' 位于 '{args.get('anchor')}' 的 {args.get('relation')} 方位 (间距: {elem['distance']}px, 坐标: ({elem['cx']}, {elem['cy']}))"
            return f"[warning] 在锚点 '{args.get('anchor')}' 的 {args.get('relation')} 方位未匹配到目标 '{args.get('target')}'"

        elif name == "scroll_probe_find":
            from .scroll_probe import scroll_and_find
            res_scroll = scroll_and_find(
                target=args.get("target", ""),
                anchor=args.get("anchor") or None,
                max_scrolls=int(args.get("max_scrolls", 6)),
                scroll_clicks=int(args.get("scroll_clicks", -4)),
            )
            return json.dumps(res_scroll, ensure_ascii=False)

        elif name == "task_checkpoint_manage":
            from .task_checkpoint import list_incomplete_tasks, rollback_task
            action = args.get("action", "list_incomplete")
            if action == "list_incomplete":
                tasks = list_incomplete_tasks()
                return f"[ok] 检查点任务列表 ({len(tasks)} 项): {json.dumps(tasks, ensure_ascii=False)}"
            elif action == "rollback":
                tid = args.get("task_id", "")
                return rollback_task(tid)
            else:
                return f"[error] 未知动作: {action}"

        elif name == "browser_cdp_action":
            from .cdp_controller import is_cdp_available, get_browser_dom_text, click_dom_element, list_browser_tabs
            action = args.get("action", "status")
            if action == "status":
                avail = is_cdp_available()
                tabs = list_browser_tabs() if avail else []
                return f"[ok] 浏览器 CDP 调试端口 9222 状态: {'开启' if avail else '未开启'} (打开标签页: {len(tabs)} 个)"
            elif action == "get_text":
                return get_browser_dom_text()
            elif action == "click_selector":
                sel = args.get("selector", "")
                return click_dom_element(sel)
            else:
                return f"[error] 未知 CDP 动作: {action}"

        elif name == "browser_default_attach":
            from .browser_connect import attach_default_browser, ensure_browser_with_cdp
            port = int(args.get("port", 9222))
            auto_restart = bool(args.get("auto_restart", False))
            target_browser = args.get("browser", "auto")
            status = ensure_browser_with_cdp(port=port, browser=target_browser, auto_restart=auto_restart)
            if not status.get("ready"):
                return f"[warning] 浏览器挂接未就绪: {status.get('message')}"
            session = attach_default_browser(port=port, browser=target_browser)
            page = session.get_active_page()
            tabs = session.list_tabs()
            b_name = status.get("browser", target_browser)
            return f"[ok] 已成功接管日常浏览器 ({b_name}，CDP 端口 {port})。活动标签页: '{page.title()}' ({page.url})，当前打开 {len(tabs)} 个标签页。"

        elif name == "browser_tabs_manage":
            from .browser_connect import attach_default_browser, get_active_browser_session
            session = get_active_browser_session() or attach_default_browser()
            action = args.get("action", "list").lower()
            if action == "list":
                tabs = session.list_tabs()
                return json.dumps(tabs, ensure_ascii=False, indent=2)
            elif action == "open":
                url = args.get("url") or args.get("target", "")
                if not url:
                    return "[error] open 操作需要提供 url 参数"
                p = session.open_or_switch_tab(url)
                return f"[ok] 已在浏览器中打开/激活页面: '{p.title()}' ({p.url})"
            elif action == "switch":
                target = args.get("target", "")
                if not target:
                    return "[error] switch 操作需要提供 target 参数 (序号或标题/网址关键字)"
                p = session.switch_tab(target)
                return f"[ok] 已成功切换至标签页: '{p.title()}' ({p.url})"
            elif action == "close":
                target = args.get("target", "")
                ok = session.close_tab(target)
                return f"[ok] 标签页 '{target}' 关闭成功" if ok else f"[warning] 未找到或未能关闭标签页 '{target}'"
            else:
                return f"[error] 未知 tabs_manage 动作: {action}"

        elif name == "browser_content_extract":
            from .browser_connect import attach_default_browser, get_active_browser_session
            session = get_active_browser_session() or attach_default_browser()
            mode = args.get("mode", "markdown")
            sel = args.get("selector", "")
            limit = int(args.get("max_chars", 4000))
            content = session.extract_page_content(mode=mode, selector=sel, max_chars=limit)
            p = session.get_active_page()
            return f"### [页面提取: {p.title()[:30]}] ({mode})\n{content}"

        elif name == "browser_eval_js":
            from .browser_connect import attach_default_browser, get_active_browser_session
            session = get_active_browser_session() or attach_default_browser()
            script = args.get("script", "")
            res = session.evaluate_script(script)
            return json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)

        elif name == "browser_list_installed":
            from .browser_connect import detect_all_installed_browsers
            installed = detect_all_installed_browsers()
            return json.dumps(installed, ensure_ascii=False, indent=2)

        elif name == "browser_explore_step":
            from .browser_connect import attach_default_browser, get_active_browser_session
            from .browser_explorer import capture_page_state, execute_step, format_page_state_for_agent
            session = get_active_browser_session() or attach_default_browser()
            page = session.get_active_page()
            act = args.get("action", "inspect").lower()
            if act == "inspect":
                state = capture_page_state(page)
                return format_page_state_for_agent(state)
            else:
                step_res = execute_step(
                    page=page,
                    action=act,
                    target=args.get("target", ""),
                    value=args.get("value", ""),
                )
                return json.dumps(step_res, ensure_ascii=False)

        elif name == "browser_compile_macro":
            from .browser_explorer import BrowserTrajectory
            from .browser_compiler import save_and_register_browser_macro
            traj = BrowserTrajectory(
                name=args.get("name", "web_macro"),
                description=args.get("description", ""),
                start_url=args.get("start_url", ""),
                steps=args.get("steps", []),
                parameters=args.get("parameters", []),
            )
            fn_name, macro_path = save_and_register_browser_macro(traj)
            return f"[ok] 浏览器自愈宏 '{fn_name}' 已成功编译并注册至 {macro_path}"

        elif name == "browser_macro_run":
            from .browser_compiler import run_browser_macro
            m_name = args.get("name", "")
            kwargs = args.get("kwargs", {})
            return run_browser_macro(m_name, **kwargs)

        else:
            return f"[error] 未知工具: {name}"






    except Exception as e:
        return f"[error] 执行工具 {name} 异常: {type(e).__name__}: {e}"