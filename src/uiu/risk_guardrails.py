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


# --------------------------------------------------------------------------
# shell 语义分类（审计 §5.3）
# --------------------------------------------------------------------------
# 原来只有正则黑名单拦「明显破坏性」命令，其余一律 SAFE —— 等于把任意命令交给模型。
# 现在按语义逐段判定：只读放行；写/删/网络/进程/系统/包管理/解释器一律要确认；
# 认不出来的命令也一律要确认（fail-safe，而不是默认放行）。

_READONLY_VERBS = frozenset({
    "dir", "ls", "ll", "pwd", "cat", "type", "head", "tail", "more", "less",
    "findstr", "grep", "rg", "find", "where", "which", "whoami", "hostname", "ver",
    "systeminfo", "tasklist", "ipconfig", "ifconfig", "netstat", "ping", "nslookup",
    "getmac", "date", "time", "echo", "wc", "sort", "uniq", "diff", "stat", "file",
    "tree", "du", "df", "ps", "top", "free", "printenv", "setx?",
})
_MUTATING_VERBS = frozenset({
    "rm", "del", "erase", "rmdir", "rd", "md", "mkdir", "move", "mv", "copy", "cp",
    "xcopy", "robocopy", "ren", "rename", "touch", "truncate", "attrib", "icacls",
    "takeown", "chmod", "chown", "ln", "mklink", "sed", "tee", "dd", "shred",
})
_NETWORK_VERBS = frozenset({
    "curl", "wget", "iwr", "invoke-restmethod", "invoke-webrequest", "start-bitstransfer",
    "ssh", "scp", "sftp", "nc", "ncat", "netcat", "telnet", "ftp", "bitsadmin",
})
_PROCESS_VERBS = frozenset({
    "taskkill", "kill", "killall", "pkill", "stop-process", "start-process", "start",
    "nohup", "wmic", "schtasks", "at",
})
_SYSTEM_VERBS = frozenset({
    "reg", "regedit", "sc", "netsh", "bcdedit", "vssadmin", "auditpol", "gpupdate",
    "net", "runas", "sudo", "su", "shutdown", "reboot", "poweroff", "halt",
})
_PACKAGE_VERBS = frozenset({
    "pip", "pip3", "npm", "yarn", "pnpm", "bun", "choco", "winget", "scoop", "apt",
    "apt-get", "yum", "dnf", "brew", "gem", "cargo", "go", "dotnet", "composer",
})
_INTERPRETER_VERBS = frozenset({
    "python", "python3", "py", "node", "deno", "perl", "ruby", "php", "lua", "rscript",
    "powershell", "pwsh", "cmd", "bash", "sh", "zsh", "wsl",
})
_READONLY_GIT_SUB = frozenset({
    "status", "diff", "log", "show", "branch", "remote", "ls-files", "rev-parse",
    "describe", "blame", "shortlog", "config", "tag",
})


def _segments(command: str) -> list[str]:
    """按 ; && || | 换行 拆成独立命令段。"""
    return [s.strip() for s in re.split("[;&|\\n]+", command) if s.strip()]


def _verbs(segment: str) -> list[str]:
    return [t.strip('"').strip("'").lower() for t in segment.split() if t.strip()]


def classify_command(command: str) -> tuple[RiskLevel, str]:
    """把一条 shell 命令按语义归类。"""
    cmd = (command or "").strip()
    if not cmd:
        return RiskLevel.SAFE, "空命令"
    low = cmd.lower()
    for pat in BLOCKED_SHELL_PATTERNS:
        if pat.search(low):
            return RiskLevel.BLOCKED, f"检测到系统级高危破坏性指令: {cmd[:80]}"

    categories: set[str] = set()
    for segment in _segments(cmd):
        tokens = _verbs(segment)
        if not tokens:
            continue
        if ">" in segment:
            categories.add("写入文件（重定向）")
        verb = tokens[0]
        rest = tokens[1:]
        if verb in _MUTATING_VERBS:
            categories.add("文件/目录写操作")
        elif verb in _NETWORK_VERBS:
            categories.add("网络访问")
        elif verb in _PROCESS_VERBS:
            categories.add("进程控制")
        elif verb in _SYSTEM_VERBS:
            categories.add("系统设置")
        elif verb in _PACKAGE_VERBS:
            categories.add("安装/包管理")
        elif verb in _INTERPRETER_VERBS:
            # 解释器可能执行任意代码：能识别的只读子命令才放行
            if verb in ("cmd", "powershell", "pwsh", "bash", "sh", "zsh") and rest:
                inner = _verbs(" ".join(rest[1:])) if rest[0].startswith(("-", "/")) else _verbs(" ".join(rest))
                if inner and inner[0] in _READONLY_VERBS:
                    continue
            categories.add("执行脚本/解释器")
        elif verb == "git":
            sub = rest[0] if rest else ""
            if sub not in _READONLY_GIT_SUB:
                categories.add("git 写操作")
        elif verb in _READONLY_VERBS:
            continue
        else:
            categories.add(f"未知命令 {verb}")

    if categories:
        return RiskLevel.CONFIRM_REQUIRED, f"命令涉及：{'、'.join(sorted(categories))}"
    return RiskLevel.SAFE, "只读命令"


def evaluate_tool_risk(name: str, args: Any) -> tuple[RiskLevel, str]:
    """Inspect tool name and argument contents to determine safety risk level."""
    args_dict = _extract_args_dict(args)

    # 1. Inspect shell_exec（语义分类，见上）
    if name in ("shell_exec", "terminal_exec", "run_command", "run_cmd"):
        cmd = str(args_dict.get("command", args_dict.get("_raw", ""))).strip()
        return classify_command(cmd)

    # 2. Inspect file access (read_file / write_file)：白名单放行、越界确认、凭据目录拒绝
    if name in ("read_file", "write_file", "delete_file", "file_write", "file_read",
                "read_spreadsheet", "write_spreadsheet", "list_dir"):
        path = str(args_dict.get("path", args_dict.get("target", ""))).strip()
        for pat in BLOCKED_PATH_PATTERNS:
            if pat.search(path):
                return RiskLevel.BLOCKED, f"严禁访问敏感机密凭证路径: '{path}'"
        writing = name in ("write_file", "delete_file", "file_write",
                           "write_spreadsheet")
        from ._sandbox import PathDecision, classify_path
        decision, why, _ = classify_path(path, for_write=writing,
                                         workspace=os.environ.get("UIU_WORKSPACE") or None)
        if decision is PathDecision.DENY:
            return RiskLevel.BLOCKED, why or f"路径不可访问: {path}"
        if decision is PathDecision.CONFIRM:
            return RiskLevel.CONFIRM_REQUIRED, why
        if writing:
            return RiskLevel.CONFIRM_REQUIRED, f"写入文件产生持久修改: '{path}'"
        return RiskLevel.SAFE, "workspace 内读取"

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
        _audit("tool_blocked", tool=name, decision="blocked",
               risk=risk.value, reason=reason, args=args)
        return False, f"[blocked] 安全卫士拦截: {reason}"

    if risk == RiskLevel.CONFIRM_REQUIRED:
        if confirm_handler is None:
            # CLI / 测试没有确认通道：保持既有行为，但留痕（谁在无人确认时放行了什么）
            _audit("tool_confirm", tool=name, decision="no_handler",
                   risk=risk.value, reason=reason, args=args)
            return True, None
        prompt = _confirm_prompt(name, args, reason)
        answer = confirm_handler(name, prompt)
        approved = str(answer).strip().lower() in ("yes", "y", "ok", "confirm", "1")
        _audit("tool_confirm", tool=name, decision="approved" if approved else "rejected",
               risk=risk.value, reason=reason, args=args)
        if not approved:
            return False, f"[cancelled] 用户拒绝执行高危操作 ({name})"

    return True, None


def _confirm_prompt(name: str, args: Any, reason: str) -> str:
    """确认框里要给足信息：完整命令 + cwd / 路径（审计 §5.3）。"""
    detail = ""
    if isinstance(args, dict):
        if args.get("command"):
            cwd = args.get("cwd") or "(默认工作目录)"
            detail = f"命令: {args['command']}\ncwd: {cwd}"
        elif args.get("path") or args.get("target"):
            detail = f"路径: {args.get('path') or args.get('target')}"
        else:
            detail = json.dumps(args, ensure_ascii=False)
    else:
        detail = str(args)
    return f"【安全风险提示】{reason}\n{detail[:400]}"


def _audit(event: str, **fields: Any) -> None:
    try:
        from .audit import record
        record(None, event, **fields)
    except Exception:
        pass
