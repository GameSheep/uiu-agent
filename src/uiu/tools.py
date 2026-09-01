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


# ----- registry -----

BUILTIN_TOOLS: dict[str, dict] = {
    "shell_exec": {"def": TOOL_SHELL_DEF, "fn": tool_shell_exec},
    "read_file": {"def": TOOL_READ_DEF, "fn": tool_read_file},
    "write_file": {"def": TOOL_WRITE_DEF, "fn": tool_write_file},
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