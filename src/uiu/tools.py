"""Built-in tools + tool registry.

Each tool is a plain Python function with a `TOOL_DEF` dict (OpenAI function-calling
schema) and an async-safe sync execute(). Skills from workspace are merged in at
runtime by agent.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# ----- built-in tool: shell -----

TOOL_SHELL_DEF = {
    "type": "function",
    "function": {
        "name": "shell_exec",
        "description": "Run a shell command and return its stdout/stderr. Use for quick inspection, git, scripts.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "cwd": {"type": "string", "description": "Working directory (optional)."},
            },
            "required": ["command"],
        },
    },
}


def tool_shell_exec(command: str, cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = result.stdout or ""
        err = result.stderr or ""
        rc = result.returncode
        combined = out + (("\n[stderr]\n" + err) if err else "")
        if rc != 0:
            combined += f"\n[exit code: {rc}]"
        return combined.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[error] command timed out after 60s"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ----- built-in tool: read_file -----

TOOL_READ_DEF = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file. Returns the content or an error message.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or workspace-relative path."}
            },
            "required": ["path"],
        },
    },
}


def tool_read_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"[error] file not found: {p}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ----- built-in tool: write_file -----

TOOL_WRITE_DEF = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write UTF-8 text to a file (overwrites). Creates parent dirs.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
}


def tool_write_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[ok] wrote {len(content)} chars to {p}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ----- built-in tool: read_spreadsheet (xlsx) -----

TOOL_SPREADSHEET_DEF = {
    "type": "function",
    "function": {
        "name": "read_spreadsheet",
        "description": "读取 Excel (.xlsx) 文件内容，直接解析文件不走屏幕 OCR，准确。返回单元格数据表格。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "xlsx 文件路径"},
                "max_rows": {"type": "integer", "description": "最多读多少行（默认50）"},
            },
            "required": ["path"],
        },
    },
}


def tool_read_spreadsheet(path: str, max_rows: int = 50) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    if not p.exists():
        return f"[error] 文件不存在: {p}"
    try:
        import openpyxl
    except ImportError:
        return "[error] 需要 openpyxl: pip install openpyxl"
    try:
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    except Exception as e:
        return f"[error] 打开失败: {type(e).__name__}: {e}"
    lines = []
    for ws in wb.worksheets:
        lines.append(f"=== 工作表: {ws.title} (max_row={ws.max_row}) ===")
        for i, row in enumerate(ws.iter_rows(max_row=max_rows, values_only=True), 1):
            cells = ["" if c is None else str(c) for c in row]
            # trim trailing empties
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                lines.append(f"  第{i}行: {' | '.join(cells)}")
        if ws.max_row and ws.max_row > max_rows:
            lines.append(f"  …（共 {ws.max_row} 行，只显示前 {max_rows} 行）")
    wb.close()
    return "\n".join(lines) if lines else "(空文件)"


# ----- registry -----

from .learning import LEARNING_TOOLS, learning_tool_defs, call_learning_tool
from .screen_tools import SCREEN_TOOLS, screen_tool_defs, call_screen_tool
from .desktop_tools import DESKTOP_TOOLS, desktop_tool_defs, call_desktop_tool
from .system_tools import SYSTEM_TOOLS, system_tool_defs, call_system_tool
from .wechat_tools import WECHAT_TOOLS, wechat_tool_defs, call_wechat_tool

BUILTIN_TOOLS: dict[str, dict] = {
    "shell_exec": {"def": TOOL_SHELL_DEF, "fn": tool_shell_exec},
    "read_file": {"def": TOOL_READ_DEF, "fn": tool_read_file},
    "write_file": {"def": TOOL_WRITE_DEF, "fn": tool_write_file},
    "read_spreadsheet": {"def": TOOL_SPREADSHEET_DEF, "fn": tool_read_spreadsheet},
    **LEARNING_TOOLS,
    **SCREEN_TOOLS,
    **DESKTOP_TOOLS,
    **SYSTEM_TOOLS,
    **WECHAT_TOOLS,
}


def tool_defs() -> list[dict]:
    return [t["def"] for t in BUILTIN_TOOLS.values()]


def call_tool(name: str, arguments_json: str, skills: list | None = None) -> str:
    if name in BUILTIN_TOOLS:
        fn = BUILTIN_TOOLS[name]["fn"]
    elif name.startswith("skill_"):
        # dispatch to skill by exec: builtin
        from .skills_runtime import try_execute
        skill_name = name[len("skill_"):]
        target = next((s for s in (skills or []) if s.name == skill_name), None)
        if target is None:
            return f"[error] unknown skill: {skill_name}"
        result = try_execute(target, arguments_json)
        if result is None:
            return f"[error] skill '{skill_name}' has no `exec:` declaration; cannot run as tool"
        return result
    else:
        return f"[error] unknown tool: {name}"
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return f"[error] tool args must be a JSON object, got {type(args).__name__}"
        return fn(**args)
    except json.JSONDecodeError as e:
        return f"[error] invalid JSON args: {e}"
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def execute(name: str, arguments_json: str, skills: list | None = None) -> str:
    return call_tool(name, arguments_json, skills=skills)