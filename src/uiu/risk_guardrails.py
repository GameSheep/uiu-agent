"""Multi-Tier Safety Guardrails & Action Sandboxing — Claude Code / Open Interpreter Pattern.

Enforces deep-inspection security policies:
1. SAFE: Read-only, inspection, or non-destructive actions.
2. CONFIRM_REQUIRED: Actions with state side-effects or external communication (file writes, wechat, process killing).
3. BLOCKED: Outright prohibited destructive commands (disk wiping, system directory purge, credential extraction).
"""

from __future__ import annotations

import enum
import json
import os
import re
from typing import Any, Callable


class RiskLevel(str, enum.Enum):
    SAFE = "SAFE"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    BLOCKED = "BLOCKED"


# Windows & Unix critical system processes that must never be terminated
CRITICAL_SYSTEM_PROCESSES = frozenset({
    "csrss.exe", "lsass.exe", "smss.exe", "services.exe",
    "wininit.exe", "svchost.exe", "winlogon.exe", "system",
    "init", "systemd", "kthreadd",
})

# Dangerous shell command patterns
BLOCKED_SHELL_PATTERNS = [
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bdiskpart\b", re.IGNORECASE),
    re.compile(r"\bfdisk\b", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\brmdir\s+.*[a-z]:\\?$", re.IGNORECASE),
    re.compile(r"\bdel\s+.*[a-z]:\\?$", re.IGNORECASE),
    re.compile(r"rm\s+-rf\s+/\s*$", re.IGNORECASE),
    re.compile(r":\(\)\s*\{", re.IGNORECASE),  # Fork bomb
    re.compile(r"\bshutdown\b", re.IGNORECASE),
    re.compile(r"\bpoweroff\b", re.IGNORECASE),
]

# Sensitive credentials and system critical targets
BLOCKED_PATH_PATTERNS = [
    re.compile(r"(^|[/\\])\.env($|[/\\])", re.IGNORECASE),
    re.compile(r"(^|[/\\])id_rsa($|[/\\])", re.IGNORECASE),
    re.compile(r"(^|[/\\])id_ed25519($|[/\\])", re.IGNORECASE),
    re.compile(r"[/\\]Windows[/\\]System32[/\\]config[/\\]SAM", re.IGNORECASE),
]

# Tools that always require user confirmation if a confirm handler is active
DEFAULT_CONFIRM_TOOLS = frozenset({
    "send_wechat",
    "send_email",
    "macro_play",
    "proc_kill",
    "kill_process",
})


def _extract_args_dict(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            val = json.loads(args)
            if isinstance(val, dict):
                return val
        except Exception:
            return {"_raw": args}
    return {}


def evaluate_tool_risk(name: str, args: Any) -> tuple[RiskLevel, str]:
    """Inspect tool name and argument contents to determine safety risk level."""
    args_dict = _extract_args_dict(args)

    # 1. Inspect shell_exec
    if name in ("shell_exec", "terminal_exec", "run_command", "run_cmd"):
        cmd = str(args_dict.get("command", args_dict.get("_raw", ""))).strip()

        for pat in BLOCKED_SHELL_PATTERNS:
            if pat.search(cmd):
                return RiskLevel.BLOCKED, f"检测到系统级高危破坏性指令: '{cmd[:60]}'"
        # Check for modifying commands
        if any(token in cmd.lower() for token in ("rm ", "del ", "rmdir ", "git push --force", "drop database")):
            return RiskLevel.CONFIRM_REQUIRED, f"命令具有修改或删除副作用: '{cmd[:60]}'"
        return RiskLevel.SAFE, "只读或常规命令行指令"

    # 2. Inspect file access (read_file / write_file)
    if name in ("read_file", "write_file", "delete_file", "file_write", "file_read"):
        path = str(args_dict.get("path", args_dict.get("target", ""))).strip()
        for pat in BLOCKED_PATH_PATTERNS:
            if pat.search(path):
                return RiskLevel.BLOCKED, f"严禁访问敏感机密凭证路径: '{path}'"

        if name in ("write_file", "delete_file", "file_write"):
            # Check system directories
            windir = os.environ.get("SystemRoot", r"C:\Windows")
            norm_path = os.path.normpath(path)
            if norm_path.lower().startswith(os.path.normpath(windir).lower()):
                return RiskLevel.BLOCKED, f"严禁修改系统核心目录: '{path}'"
            return RiskLevel.CONFIRM_REQUIRED, f"写入文件产生持久修改: '{path}'"

    # 3. Inspect process kill
    if name in ("proc_kill", "kill_process", "process_terminate"):
        target = str(args_dict.get("name", args_dict.get("pid", ""))).lower()
        for proc in CRITICAL_SYSTEM_PROCESSES:
            if proc in target:
                return RiskLevel.BLOCKED, f"严禁终止操作系统核心关键进程: '{target}'"
        return RiskLevel.CONFIRM_REQUIRED, f"终止系统进程: '{target}'"

    # 4. External communications & known sensitive tools
    if name in DEFAULT_CONFIRM_TOOLS:
        return RiskLevel.CONFIRM_REQUIRED, f"触发外部通信或敏感操作: {name}"

    # Default to SAFE
    return RiskLevel.SAFE, "常规非破坏性操作"


def intercept_tool_call(
    name: str,
    args: Any,
    confirm_handler: Callable[[str, str], str] | None = None,
) -> tuple[bool, str | None]:
    """Guardrail interception gate.

    Returns:
        (allowed: bool, rejection_reason: str | None)
    """
    risk, reason = evaluate_tool_risk(name, args)

    if risk == RiskLevel.BLOCKED:
        return False, f"[blocked] 安全卫士拦截: {reason}"

    if risk == RiskLevel.CONFIRM_REQUIRED and confirm_handler is not None:
        args_str = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
        prompt = f"【安全风险提示】{reason}\n参数: {args_str[:120]}"
        answer = confirm_handler(name, prompt)
        if str(answer).strip().lower() not in ("yes", "y", "ok", "confirm", "1"):
            return False, f"[cancelled] 用户拒绝执行高危操作 ({name})"

    return True, None
