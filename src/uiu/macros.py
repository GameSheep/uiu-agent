"""Macro tools — record/play/list/remove keyboard-mouse macros.

宏 = workspace/macros/<name>.json 的步骤序列。既可由 macro_record 录制，
也可由 agent 直接 write_file 生成（AI 写自动化脚本）再 macro_play 执行。
"""

from __future__ import annotations

from . import paths

import json
import re
import time
from pathlib import Path

from .macro_player import play_steps
from .macro_recorder import MacroRecorder, load_macro, macros_dir, save_macro

# 录制停止键默认 F9；最长录制 30 分钟兜底
DEFAULT_STOP_KEY = "F9"
MAX_RECORD_SECONDS = 1800


def _workspace_root() -> Path | None:
    """Locate active workspace (same resolution as learning._ws)."""
    import os
    env = os.environ.get("UIU_WORKSPACE")
    if env:
        return Path(env).expanduser()
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", paths.home_workspace()):
        if cand.is_dir():
            return cand
    return None


def _macro_path(name: str) -> Path | None:
    root = _workspace_root()
    if root is None:
        return None
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (name or "").strip())
    if not safe:
        return None
    return macros_dir(root) / f"{safe}.json"


def _valid_name(name: str) -> str | None:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", (name or "").strip()).strip("_")
    return safe[:64] or None


# ---------- tool bodies ----------

def macro_record(name: str, description: str = "", timeout: int = 0) -> str:
    """Record a macro until F9 is pressed. Blocks the caller."""
    safe = _valid_name(name)
    if not safe:
        return "[error] 宏名非法（仅字母/数字/_/-）"
    path = _macro_path(safe)
    if path is None:
        return "[error] 无 workspace，无法录制"
    timeout = max(0, min(int(timeout or 0), MAX_RECORD_SECONDS))
    rec = MacroRecorder(timeout=timeout)
    try:
        steps, aborted = rec.run()
    except Exception as e:
        return f"[error] 录制失败: {type(e).__name__}: {e}"
    if not steps and not aborted:
        return "(录制超时且无操作，未保存)"
    save_macro(path, safe, (description or "").strip(), steps)
    n = len(steps)
    note = "（F9 停止）" if aborted else "（超时自动停）"
    return f"[ok] 已录制宏 '{safe}'：{n} 步{note} → {path.name}"


def macro_play(name: str, speed: float = 1.0, start: int = 0, end: int = 0) -> str:
    """Play a recorded macro by name."""
    safe = _valid_name(name)
    if not safe:
        return "[error] 宏名非法"
    path = _macro_path(safe)
    if path is None or not path.exists():
        return f"[error] 宏不存在: {safe}（先 macro_record 或写 workspace/macros/{safe}.json）"

    from .desktop_guard import check_desktop_action_allowed
    allowed, reason = check_desktop_action_allowed("macro_play")
    if not allowed:
        return f"[error] {reason}"
    try:
        macro = load_macro(path)
    except Exception as e:
        return f"[error] 宏文件损坏: {e}"
    n_total = len(macro.get("steps", []))
    played, status = play_steps(
        macro.get("steps", []), speed=max(0.1, float(speed or 1.0)),
        start=start, end=end or None)
    if status.startswith("[error]"):
        return status
    # 回放成功 → 记录使用（供 /suggestions 发现常用宏 → 建议定时化）
    try:
        root = _workspace_root()
        if root is not None:
            from .suggestions import record_macro_play
            record_macro_play(root, safe)
    except Exception:
        pass
    return f"{status}（宏 '{safe}' 共 {n_total} 步）"


def macro_list() -> str:
    """List saved macros with step counts and descriptions."""
    root = _workspace_root()
    if root is None:
        return "(无 workspace)"
    d = macros_dir(root)
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            m = load_macro(p)
            out.append(f"- {p.stem}  {len(m.get('steps', []))} 步  {m.get('description', '')[:80]}")
        except Exception:
            out.append(f"- {p.stem}  (文件损坏)")
    return "\n".join(out) if out else "(无宏 — macro_record 录一个，或直接写 workspace/macros/<name>.json)"


def macro_remove(name: str) -> str:
    """删除宏：默认移入回收站（uiu trash --restore 可找回）。"""
    safe = _valid_name(name)
    if not safe:
        return "[error] 宏名非法"
    path = _macro_path(safe)
    if path is None or not path.exists():
        return f"[error] 宏不存在: {safe}"
    try:
        from .trash import add_file
        add_file(path.parent.parent, path, kind="macro", label=safe)
        return f"[ok] 已删除宏 '{safe}'（已移入回收站，uiu trash 可恢复）"
    except Exception as e:
        return f"[error] 删除失败: {e}"


def quick_macro_listen(action: str = "start") -> str:
    """Start or stop the background QuickMacro (按键精灵) hotkey daemon.

    - F10: Start / Stop recording loop
    - F12: Instant replay (Single play, or Ctrl+F12 for 10 loops)
    - F11: Emergency abort at any time
    """
    from .quick_macro import start_quick_macro_daemon, stop_quick_macro_daemon
    action = (action or "start").lower().strip()
    root = _workspace_root()
    if action in ("stop", "off", "close"):
        stop_quick_macro_daemon()
        return "[ok] 按键精灵监听已停止"

    try:
        start_quick_macro_daemon(workspace_root=root)
        return (
            "[ok] 极速按键精灵已启动全局热键监听！\n"
            "操作指南（伴随系统蜂鸣音）：\n"
            "1. 切换到目标软件起始位置，按 [F10] 开始录制（单声蜂鸣）\n"
            "2. 人工手动操作一轮循环后，再次按 [F10] 结束并封包（双声蜂鸣）\n"
            "3. 按 [F12] 立即以原生速度单次回放；按 [Ctrl+F12] 循环执行 10 次\n"
            "4. 任何时候按 [F11] 瞬间紧急刹车"
        )
    except Exception as e:
        return f"[error] 启动按键精灵失败: {e}"


def macro_detect_pattern(name: str = "_quick_loop", save_as: str = "") -> str:
    """Detect repetitive loop pattern in a recorded macro and extract minimal loop body."""
    from .pattern_detector import detect_repeating_loop
    safe = _valid_name(name)
    if not safe:
        return "[error] 宏名非法"
    path = _macro_path(safe)
    if path is None or not path.exists():
        return f"[error] 宏不存在: {safe}"

    try:
        macro = load_macro(path)
    except Exception as e:
        return f"[error] 宏文件损坏: {e}"

    steps = macro.get("steps", [])
    res = detect_repeating_loop(steps)
    if not res.get("found"):
        return f"[提示] {res.get('summary')}"

    loop_steps = res["loop_steps"]
    target_name = _valid_name(save_as) if save_as else f"{safe}_loop"
    target_path = _macro_path(target_name)
    if target_path:
        save_macro(target_path, target_name, f"从 {safe} 提取的最小循环宏 (周期 {res['period']} 步)", loop_steps)
        return (
            f"[ok] {res.get('summary')}\n"
            f"已保存提取后的循环宏至 '{target_name}'（共 {len(loop_steps)} 步，原序列包含 {res['repetitions']} 轮重复）。\n"
            f"现在可直接按 F12 或使用 macro_play('{target_name}') 进行极速回放。"
        )
    return f"[ok] {res.get('summary')} (未能写入文件)"


# ---------- tool defs (OpenAI function schema) ----------

MACRO_RECORD_DEF = {
    "type": "function",
    "function": {
        "name": "macro_record",
        "description": "录制一段鼠标键盘操作存为宏（按 F9 结束录制）。录制时请用户先切到目标窗口再开始，录完可 macro_play 回放。适合把重复性 GUI 操作变成可复用宏。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "宏名（字母数字_-）"},
                "description": {"type": "string", "description": "这个宏干什么用"},
                "timeout": {"type": "integer", "description": "自动停止秒数（默认 0=等 F9）"},
            },
            "required": ["name"],
        },
    },
}

MACRO_PLAY_DEF = {
    "type": "function",
    "function": {
        "name": "macro_play",
        "description": "回放一个已录制的宏（真实控制鼠标键盘）。执行前必须先向用户确认目标窗口已就绪；回放中甩鼠标到屏幕左上角或按 F9 可紧急中止。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "speed": {"type": "number", "description": "倍速（2=快一倍，0.5=慢一倍）"},
                "start": {"type": "integer", "description": "从第几步开始（1 起）"},
                "end": {"type": "integer", "description": "到第几步结束"},
            },
            "required": ["name"],
        },
    },
}

MACRO_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "macro_list",
        "description": "列出所有已保存的宏及步数、描述。",
        "parameters": {"type": "object", "properties": {}},
    },
}

MACRO_REMOVE_DEF = {
    "type": "function",
    "function": {
        "name": "macro_remove",
        "description": "删除一个宏。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
}

QUICK_MACRO_LISTEN_DEF = {
    "type": "function",
    "function": {
        "name": "quick_macro_listen",
        "description": "启动或停止经典按键精灵全局热键监听模式。用户按下 F10 开始/结束录制，按 F12 毫秒级单次回放，Ctrl+F12 循环 10 次，F11 随时紧急刹车。当用户说'我要做重复操作/帮我记一下动作'时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop"],
                    "description": "启动或停止监听（默认 start）",
                }
            },
        },
    },
}

MACRO_DETECT_PATTERN_DEF = {
    "type": "function",
    "function": {
        "name": "macro_detect_pattern",
        "description": "分析已录制的宏，自动挖掘重复出现的动作序列，剥离多余的前置/后置动作，提取出纯净的最小单次循环宏。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "待分析的宏名称（默认 _quick_loop）"},
                "save_as": {"type": "string", "description": "提取出的循环宏保存名称（可选）"},
            },
        },
    },
}

MACRO_TOOLS: dict[str, dict] = {
    "macro_record": {"def": MACRO_RECORD_DEF, "fn": macro_record},
    "macro_play": {"def": MACRO_PLAY_DEF, "fn": macro_play},
    "macro_list": {"def": MACRO_LIST_DEF, "fn": macro_list},
    "macro_remove": {"def": MACRO_REMOVE_DEF, "fn": macro_remove},
    "quick_macro_listen": {"def": QUICK_MACRO_LISTEN_DEF, "fn": quick_macro_listen},
    "macro_detect_pattern": {"def": MACRO_DETECT_PATTERN_DEF, "fn": macro_detect_pattern},
}


def macro_tool_defs() -> list[dict]:
    return [t["def"] for t in MACRO_TOOLS.values()]


def call_macro_tool(name: str, arguments_json: str) -> str:
    if name not in MACRO_TOOLS:
        return f"[error] unknown macro tool: {name}"
    fn = MACRO_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
