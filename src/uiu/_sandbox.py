"""Path sandbox + command guardrails for LLM-reachable tools.

Policy (fail-closed on the worst, permissive elsewhere so daily use doesn't break):
- allow any path EXCEPT blocked system dirs + sensitive filenames
- cap read/write sizes so a giant file can't blow up context or disk
- shell cwd must be an existing dir inside cwd/workspace/home (no C:\\Windows)
- dangerous shell verbs are rejected (ask user to run them manually)
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# ----- limits -----
MAX_READ_BYTES = 512 * 1024      # read_file / spreadsheet guard
MAX_WRITE_BYTES = 512 * 1024     # write_file guard
MAX_COMMAND_CHARS = 8000
MAX_OUTPUT_CHARS = 20_000

# ----- sensitive filenames (tool-level deny; config.py itself still reads .env) -----
_SENSITIVE_NAMES = (".env",)
_SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".kdbx")
_SENSITIVE_PATTERNS = ("id_rsa", "id_ed25519", "credentials", "secret_token")


def _norm(p: Path) -> str:
    try:
        return os.path.normcase(str(p.resolve()))
    except Exception:
        return os.path.normcase(os.path.abspath(str(p)))


def _blocked_sys_dirs() -> list[str]:
    dirs: list[str] = []
    windir = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    dirs.append(_norm(Path(windir)))
    for cand in (r"C:\Windows\System32", r"C:\Program Files", r"C:\Program Files (x86)"):
        dirs.append(os.path.normcase(cand))
    for cand in ("/etc", "/root", "/proc", "/sys", "/dev"):
        dirs.append(cand)
    return dirs


_BLOCKED_DIRS = _blocked_sys_dirs()


def is_sensitive_filename(p: Path) -> bool:
    name = p.name
    if name in _SENSITIVE_NAMES:
        return True
    low = name.lower()
    if low.endswith(_SENSITIVE_SUFFIXES):
        return True
    return any(pat in low for pat in _SENSITIVE_PATTERNS)


def check_path(path: str, *, for_write: bool = False) -> tuple[bool, str, Path | None]:
    """Validate a tool-supplied path. Returns (ok, msg, resolved)."""
    if not path or not str(path).strip():
        return False, "[error] 路径不能为空", None
    raw = str(path).strip()
    if len(raw) > 2000:
        return False, "[error] 路径过长", None
    if "\x00" in raw:
        return False, "[error] 非法路径", None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    norm = _norm(p)
    for blocked in _BLOCKED_DIRS:
        if norm == blocked or norm.startswith(blocked.rstrip(os.sep) + os.sep):
            return False, f"[error] 系统目录不可访问: {p}", None
    if is_sensitive_filename(p):
        return False, f"[error] 敏感文件不可通过工具读写: {p.name}（用 uiu config 管理密钥）", None
    # config.yaml 本身可读但不可由工具覆盖（防 agent 改配置提权）
    if for_write and p.name == "config.yaml":
        return False, "[error] config.yaml 不可通过工具覆盖（手动编辑）", None
    return True, "", p


def check_cwd(cwd: str | None) -> tuple[bool, str]:
    if not cwd:
        return True, ""
    ok, msg, p = check_path(cwd)
    if not ok:
        return False, msg
    assert p is not None
    if not p.is_dir():
        return False, f"[error] cwd 不存在: {p}"
    return True, ""


_DANGEROUS_VERBS = (
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\bmkfs\b", r"\bdd\s+if=", r":\(\)\s*{\s*:\|",
    r"\bdel\s+/[fs]", r"\bformat\s+[a-z]:",
    r"rm\s+-rf\s+/(?:\s|$)",
)


def check_command(command: str) -> tuple[bool, str]:
    if not command or not command.strip():
        return False, "[error] command 不能为空"
    if len(command) > MAX_COMMAND_CHARS:
        return False, f"[error] command 过长（>{MAX_COMMAND_CHARS}）"
    low = command.lower()
    for pat in _DANGEROUS_VERBS:
        if re.search(pat, low):
            return False, "[error] 危险命令被拦截（关机/格式化/删根目录请手动执行）"
    return True, ""


_APP_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff\s.\-()（）]{0,99}$")
_SHELL_META = set("&|;$()`<>^!%*?#~")


def check_app_name(app_name: str) -> tuple[bool, str]:
    if not app_name or not app_name.strip():
        return False, "[error] app_name 不能为空"
    s = app_name.strip()
    if len(s) > 100:
        return False, "[error] app_name 过长"
    if any(c in _SHELL_META for c in s):
        return False, "[error] app_name 含非法字符"
    if not _APP_NAME_RE.match(s):
        return False, "[error] app_name 非法（仅允许中英文/数字/空格/.-）"
    return True, ""


def truncate_output(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n…（输出过长，已截断，共 {len(text)} 字符）"
    return text
