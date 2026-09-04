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
    from ._sandbox import check_command, check_cwd, truncate_output
    ok, msg = check_command(command)
    if not ok:
        return msg
    ok, msg = check_cwd(cwd)
    if not ok:
        return msg
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,  # 交互式命令直接 EOF，不悬挂等输入（如 Windows date）
        )
        out = result.stdout or ""
        err = result.stderr or ""
        rc = result.returncode
        combined = out + (("\n[stderr]\n" + err) if err else "")
        if rc != 0:
            combined += f"\n[exit code: {rc}]"
        combined = combined.strip() or "(no output)"
        return truncate_output(combined)
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
    from ._sandbox import MAX_READ_BYTES, check_path
    ok, msg, p = check_path(path)
    if not ok:
        return msg
    assert p is not None
    try:
        if p.stat().st_size > MAX_READ_BYTES:
            return f"[error] 文件过大（>{MAX_READ_BYTES // 1024}KB），用 read_spreadsheet 分段读或 shell 分片查看"
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
    from ._sandbox import MAX_WRITE_BYTES, check_path
    if len(content.encode("utf-8", errors="replace")) > MAX_WRITE_BYTES:
        return f"[error] 内容过大（>{MAX_WRITE_BYTES // 1024}KB），请分多次写入"
    ok, msg, p = check_path(path, for_write=True)
    if not ok:
        return msg
    assert p is not None
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
    from ._sandbox import check_path
    ok, msg, p = check_path(path)
    if not ok:
        return msg
    assert p is not None
    max_rows = max(1, min(int(max_rows or 50), 500))
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
from .desktop_tools import get_all_tool_schemas, dispatch_tool
from .system_tools import SYSTEM_TOOLS, system_tool_defs, call_system_tool
from .wechat_tools import WECHAT_TOOLS, wechat_tool_defs, call_wechat_tool
from .ime_tools import IME_TOOLS, ime_tool_defs, call_ime_tool
from .agent_tools import AGENT_TOOLS, agent_tool_defs, call_agent_tool
from .askui_tools import ASKUI_TOOLS, askui_tool_defs, call_askui_tool
from .browser_tools import BROWSER_TOOLS, browser_tool_defs, call_browser_tool
from .voice_tools import VOICE_TOOLS, voice_tool_defs, call_voice_tool
from .memory_rag import MEMORY_TOOLS, memory_tool_defs, call_memory_tool
from .delegation import DELEGATION_TOOLS, delegation_tool_defs
from .web_tools import WEB_TOOLS, web_tool_defs
from .proc_tools import PROC_TOOLS, proc_tool_defs
from .skills_runtime import SKILL_INDEX_TOOLS
from .clarify import CLARIFY_TOOLS

# 兼容层：新 desktop API（DESKTOP_TOOL_SCHEMAS + dispatch_tool）桥接到
# 旧注册表形状。send_wechat 排除在外——它经 WECHAT_TOOLS 注册，避免重复。
def _desktop_fn(name):
    def fn(**kwargs):
        return dispatch_tool(name, kwargs)
    fn.__name__ = f"desktop_{name}"
    return fn


DESKTOP_TOOLS: dict[str, dict] = {
    d["function"]["name"]: {"def": d, "fn": _desktop_fn(d["function"]["name"])}
    for d in get_all_tool_schemas()
    if d.get("function", {}).get("name") not in ("send_wechat",)
}


def desktop_tool_defs() -> list[dict]:
    return get_all_tool_schemas()


def call_desktop_tool(name: str, arguments_json: str) -> str:
    import json as _json
    try:
        args = _json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return dispatch_tool(name, args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


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
    **IME_TOOLS,
    **AGENT_TOOLS,
    **ASKUI_TOOLS,
    **BROWSER_TOOLS,
    **VOICE_TOOLS,
    **MEMORY_TOOLS,
    **DELEGATION_TOOLS,
    **WEB_TOOLS,
    **PROC_TOOLS,
    **SKILL_INDEX_TOOLS,
    **CLARIFY_TOOLS,
}


def tool_defs() -> list[dict]:
    """Get all tool definitions including dynamic MCP tools."""
    base = [t["def"] for t in BUILTIN_TOOLS.values()]
    # Add MCP tools if connected
    try:
        from .mcp_tools import mcp_tool_defs_list
        base.extend(mcp_tool_defs_list())
    except Exception:
        pass
    return base


def tool_groups() -> list[tuple[str, list[str]]]:
    """Tools grouped by category (for the startup banner, Hermes-style)."""
    order: list[tuple[str, object]] = [
        ("base", ["shell_exec", "read_file", "write_file", "read_spreadsheet"]),
        ("proc", PROC_TOOLS),
        ("learn", LEARNING_TOOLS),
        ("skills", SKILL_INDEX_TOOLS),
        ("ask", CLARIFY_TOOLS),
        ("screen", SCREEN_TOOLS),
        ("desktop", DESKTOP_TOOLS),
        ("system", SYSTEM_TOOLS),
        ("web", WEB_TOOLS),
        ("browser", BROWSER_TOOLS),
        ("wechat", WECHAT_TOOLS),
        ("ime", IME_TOOLS),
        ("subagent", DELEGATION_TOOLS),
        ("agent", AGENT_TOOLS),
        ("cv", ASKUI_TOOLS),
        ("voice", VOICE_TOOLS),
        ("memory", MEMORY_TOOLS),
    ]
    out: list[tuple[str, list[str]]] = []
    for label, src in order:
        if isinstance(src, dict):
            names = [k for k in src if k in BUILTIN_TOOLS]
        else:
            names = [k for k in src if k in BUILTIN_TOOLS]
        if names:
            out.append((label, names))
    try:
        from .mcp_tools import get_mcp_tools
        mcp_names = sorted(get_mcp_tools())
        if mcp_names:
            out.append(("mcp", mcp_names))
    except Exception:
        pass
    return out


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
    elif name.startswith("mcp_"):
        # dispatch to MCP server
        from .mcp_client import mcp_call_tool_sync
        return mcp_call_tool_sync(name, arguments_json)
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