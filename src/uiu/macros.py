"""Macro tools — record/play/list/remove keyboard-mouse macros.

宏 = workspace/macros/<name>.json 的步骤序列。既可由 macro_record 录制，
也可由 agent 直接 write_file 生成（AI 写自动化脚本）再 macro_play 执行。
"""

from __future__ import annotations

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
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", Path.home() / ".uiu" / "workspace"):
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
    """Delete a saved macro."""
    safe = _valid_name(name)
    if not safe:
        return "[error] 宏名非法"
    path = _macro_path(safe)
    if path is None or not path.exists():
        return f"[error] 宏不存在: {safe}"
    try:
        path.unlink()
        return f"[ok] 已删除宏 '{safe}'"
    except OSError as e:
        return f"[error] 删除失败: {e}"


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

MACRO_TOOLS: dict[str, dict] = {
    "macro_record": {"def": MACRO_RECORD_DEF, "fn": macro_record},
    "macro_play": {"def": MACRO_PLAY_DEF, "fn": macro_play},
    "macro_list": {"def": MACRO_LIST_DEF, "fn": macro_list},
    "macro_remove": {"def": MACRO_REMOVE_DEF, "fn": macro_remove},
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
