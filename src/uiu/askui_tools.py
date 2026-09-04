"""AskUI integration — desktop app automation via Computer Vision.

AskUI uses Computer Use Agents (CUA) to automate any desktop application
without selectors or instrumentation. It works on whatever is visible on screen.

Tools:
- look: screenshot + analyze screen state (windows, text, coordinates)
- askui_autopilot: execute a natural language instruction on the desktop

Install:
    pip install askui
    # or: uv add askui
"""

from __future__ import annotations

import time


# ---------- look: screen analysis ----------

def look(region: str = "full") -> str:
    """Take a screenshot and analyze the current screen state.

    Returns: foreground window, all visible windows, OCR text with coordinates.
    Use this BEFORE and AFTER every action to verify state changes.

    region: full/left/right/top/bottom/center — which area to analyze
    """
    import win32gui
    from .screen_tools import _screenshot, _ocr_image

    # Get foreground window
    fg_hwnd = win32gui.GetForegroundWindow()
    fg_title = win32gui.GetWindowText(fg_hwnd)

    # Get all visible windows
    windows = []
    def _enum(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t.strip():
                windows.append(t)
    win32gui.EnumWindows(_enum, None)

    # Screenshot + OCR
    path = _screenshot()
    items = _ocr_image(path)

    # Filter by region if needed
    if region != "full":
        import pyautogui
        sw, sh = pyautogui.size()
        half_w, half_h = sw // 2, sh // 2
        regions = {
            "left": (0, 0, half_w, sh),
            "right": (half_w, 0, half_w, sh),
            "top": (0, 0, sw, half_h),
            "bottom": (0, half_h, sw, half_h),
            "center": (sw // 4, sh // 4, sw // 2, sh // 2),
        }
        if region in regions:
            x, y, w, h = regions[region]
            filtered = []
            for item in items:
                cx, cy = item["cx"], item["cy"]
                if x <= cx <= x + w and y <= cy <= y + h:
                    filtered.append(item)
            items = filtered

    # Format output
    lines = [
        f"前台窗口: {fg_title}",
        f"可见窗口 ({len(windows)}):",
    ]
    for w in windows[:15]:
        lines.append(f"  - {w}")
    if len(windows) > 15:
        lines.append(f"  ... 还有 {len(windows) - 15} 个")

    lines.append(f"\n屏幕文字 ({len(items)} 个):")
    for item in items:
        lines.append(f"  '{item['text']}' @ ({int(item['cx'])},{int(item['cy'])})")

    return "\n".join(lines)


# ---------- askui_autopilot: natural language desktop control ----------

def askui_autopilot(instruction: str) -> str:
    """Execute a natural language instruction on the desktop using AskUI.

    AskUI uses Computer Vision to find and interact with UI elements.
    Works on any desktop application (WeChat, Office, Notepad, etc.)

    instruction: what to do, e.g.:
        - "点击微信的文件传输助手"
        - "在记事本中输入 hello world"
        - "打开计算器"
    """
    try:
        from askui import AiElement
        from askui.anthropic import ClaudeComputerAgent
        from askui.tools import AnthropicComputerTool
    except ImportError:
        return "[error] AskUI 未安装。运行: pip install askui"

    try:
        # Initialize agent with Claude
        agent = ClaudeComputerAgent(tools=[AnthropicComputerTool()])

        # Execute the instruction
        result = agent.act(instruction)

        return f"[ok] AskUI 执行完成: {instruction}\n结果: {str(result)[:200]}"
    except Exception as e:
        return f"[error] AskUI 执行失败: {type(e).__name__}: {e}"


# ---------- tool definitions ----------

LOOK_DEF = {
    "type": "function",
    "function": {
        "name": "look",
        "description": "截图分析当前屏幕状态。返回前台窗口、所有可见窗口、屏幕文字及坐标。每次操作前后调用以验证状态。",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "enum": ["full", "left", "right", "top", "bottom", "center"],
                    "description": "分析区域（默认 full 全屏）",
                },
            },
        },
    },
}

ASKUI_AUTOPILOT_DEF = {
    "type": "function",
    "function": {
        "name": "askui_autopilot",
        "description": "用 AskUI 在桌面执行自然语言指令。通过 Computer Vision 操作任何桌面软件（微信、Office、记事本等）。例：'点击微信的文件传输助手'",
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "要执行的操作描述（中文或英文）",
                },
            },
            "required": ["instruction"],
        },
    },
}


ASKUI_TOOLS: dict[str, dict] = {
    "look": {"def": LOOK_DEF, "fn": look},
    "askui_autopilot": {"def": ASKUI_AUTOPILOT_DEF, "fn": askui_autopilot},
}


def askui_tool_defs() -> list[dict]:
    return [t["def"] for t in ASKUI_TOOLS.values()]


def call_askui_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in ASKUI_TOOLS:
        return f"[error] unknown askui tool: {name}"
    fn = ASKUI_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
