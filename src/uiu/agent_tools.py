"""External agent CLI delegation — call Claude Code / Codex from uiu agent.

Delegate coding tasks to external agent CLIs in non-interactive mode:

- claude:  claude --print --dangerously-skip-permissions --output-format text
- codex:   codex exec --dangerously-bypass-approvals-and-sandbox

Usage:
  delegate(agent="claude", task="Fix the bug in foo.py")
  delegate(agent="codex", task="Add tests for bar module", cwd="E:/project")
"""

from __future__ import annotations

import shutil
import subprocess


def delegate(agent: str, task: str, cwd: str | None = None, model: str | None = None, timeout: int = 300) -> str:
    """Run an external agent CLI (claude / codex) non-interactively."""
    agent = (agent or "").lower().strip()
    if agent not in ("claude", "codex"):
        return f"[error] unsupported agent: {agent}. Available: claude, codex"
    task = (task or "").strip()
    if not task:
        return "[error] task 不能为空"
    if len(task) > 20000:
        return "[error] task 过长（>20000）"
    if model and len(model) > 200:
        return "[error] model 过长"
    try:
        timeout = max(10, min(int(timeout or 300), 1800))
    except (TypeError, ValueError):
        return "[error] timeout 须为数字"
    if cwd:
        from ._sandbox import check_cwd
        ok, msg = check_cwd(cwd)
        if not ok:
            return msg

    if agent == "claude":
        return _run_claude(task, cwd, model, timeout)
    else:
        return _run_codex(task, cwd, model, timeout)


def _run_claude(task: str, cwd: str | None, model: str | None, timeout: int) -> str:
    """Run claude --print in non-interactive mode."""
    import shutil
    if not shutil.which("claude"):
        return "[error] claude CLI not found. Install: npm install -g @anthropic-ai/claude-code"

    argv = ["claude", "--print", "--dangerously-skip-permissions", "--output-format", "text"]
    if model:
        argv += ["--model", model]
    argv.append(task)

    return _subprocess_run(argv, cwd, timeout, "claude")


def _run_codex(task: str, cwd: str | None, model: str | None, timeout: int) -> str:
    """Run codex exec in non-interactive mode."""
    import shutil
    if not shutil.which("codex"):
        return "[error] codex CLI not found. Install: cargo install codex-rs (or see https://github.com/openai/codex)"

    argv = ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"]
    if model:
        argv += ["--model", model]
    argv.append(task)

    return _subprocess_run(argv, cwd, timeout, "codex")


def _shell_quote(s: str) -> str:
    """Quote a string for Windows / POSIX shell safety."""
    import re
    if not s:
        return '""'
    # If safe alphanumerics, no quote needed
    if re.match(r'^[\w./\-:@]+$', s):
        return s
    # Windows: wrap in quotes, escape embedded quotes
    return '"' + s.replace('"', '\\"') + '"'


def _subprocess_run(argv: list[str], cwd: str | None, timeout: int, label: str) -> str:
    """Shared subprocess runner (argv list, shell=False — no shell injection)."""
    import os
    import subprocess
    # Windows 上 .cmd/.bat 包裹器需经 cmd /d /c 启动，但仍用 argv 列表传参
    run_argv: list[str] | str = argv
    if os.name == "nt":
        import shutil
        resolved = shutil.which(argv[0])
        if resolved and resolved.lower().endswith((".cmd", ".bat")):
            run_argv = ["cmd", "/d", "/c", resolved, *argv[1:]]
    try:
        result = subprocess.run(
            run_argv,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            stdin=subprocess.DEVNULL,
        )
        out = result.stdout or ""
        err = result.stderr or ""
        rc = result.returncode
        combined = out
        if err.strip():
            combined += ("\n" if combined else "") + f"[stderr]\n{err}"
        if rc != 0:
            combined += f"\n[exit code: {rc}]"
        return combined.strip() or f"({label} finished with no output)"
    except subprocess.TimeoutExpired:
        return f"[error] {label} timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"[error] {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def list_agents() -> str:
    """Check which external agent CLIs are available on this system."""
    agents = {
        "claude": "claude",
        "codex": "codex",
    }
    found = []
    missing = []
    for name, binary in agents.items():
        path = shutil.which(binary)
        if path:
            found.append(f"  [ok] {name}: {path}")
        else:
            missing.append(f"  [--] {name}: not found")
    lines = ["Installed agents:"]
    lines.extend(found)
    if missing:
        lines.append("Not installed:")
        lines.extend(missing)
    return "\n".join(lines)


# ---------- tool definitions ----------

DELEGATE_DEF = {
    "type": "function",
    "function": {
        "name": "delegate",
        "description": "把编程任务委派给外部 agent CLI（Claude Code 或 Codex）非交互执行。适合大型/独立任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["claude", "codex"],
                    "description": "用哪个 agent：claude（Claude Code）或 codex（OpenAI Codex）",
                },
                "task": {
                    "type": "string",
                    "description": "要交给外部 agent 完成的任务描述（会当 prompt 传入）",
                },
                "cwd": {
                    "type": "string",
                    "description": "工作目录（可选，默认当前目录）",
                },
                "model": {
                    "type": "string",
                    "description": "指定模型（可选，如 claude 的 'sonnet' 或 codex 的 'o3'）",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数（默认 300 秒）",
                },
            },
            "required": ["agent", "task"],
        },
    },
}

LIST_AGENTS_DEF = {
    "type": "function",
    "function": {
        "name": "list_agents",
        "description": "列出本机已安装的外部 agent CLI（claude / codex）",
        "parameters": {"type": "object", "properties": {}},
    },
}


AGENT_TOOLS: dict[str, dict] = {
    "delegate": {"def": DELEGATE_DEF, "fn": delegate},
    "list_agents": {"def": LIST_AGENTS_DEF, "fn": list_agents},
}


def agent_tool_defs() -> list[dict]:
    return [t["def"] for t in AGENT_TOOLS.values()]


def call_agent_tool(name: str, arguments_json: str) -> str:
    import json
    if name not in AGENT_TOOLS:
        return f"[error] unknown agent tool: {name}"
    fn = AGENT_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return "[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
