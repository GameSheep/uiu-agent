"""Path sandbox + command guardrails for LLM-reachable tools.

Policy (fail-closed on the worst, permissive elsewhere so daily use doesn't break):
- allow any path EXCEPT blocked system dirs + sensitive filenames
- cap read/write sizes so a giant file can't blow up context or disk
- shell cwd must be an existing dir inside cwd/workspace/home (no C:\\Windows)
- dangerous shell verbs are rejected (ask user to run them manually)
"""

from __future__ import annotations

from . import paths

import enum
import os
import re
import tempfile
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


class PathDecision(str, enum.Enum):
    """路径访问决策：白名单内放行 / 越界需用户确认 / 一律拒绝。"""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


def _credential_dirs() -> list[str]:
    """凭据类目录：里面的东西（cookie / 凭据库 / 私钥）一律不给工具碰。"""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    cands = [
        home / ".ssh", home / ".aws", home / ".gnupg", home / ".kube",
        home / ".config" / "gcloud", paths.uiu_home(),
        appdata / "Microsoft" / "Credentials",
        local / "Microsoft" / "Credentials",
        local / "Google" / "Chrome" / "User Data",
        appdata / "Mozilla" / "Firefox" / "Profiles",
        appdata / "Opera Software", local / "BraveSoftware",
    ]
    return [os.path.normcase(str(c)) for c in cands]


_CREDENTIAL_DIRS = _credential_dirs()


def _allowed_roots(workspace: Path | str | None = None) -> list[str]:
    """放行区：workspace、当前工作目录、系统临时目录。"""
    roots = [Path.cwd(), Path(tempfile.gettempdir())]
    if workspace:
        roots.append(Path(workspace))
    env_ws = os.environ.get("UIU_WORKSPACE", "").strip()
    if env_ws:
        roots.append(Path(env_ws))
    return [os.path.normcase(str(r)) for r in roots]


def _under(norm: str, root: str) -> bool:
    return norm == root or norm.startswith(root.rstrip(os.sep) + os.sep)


def classify_path(path: str, *, for_write: bool = False,
                  workspace: Path | str | None = None) -> tuple[PathDecision, str, Path | None]:
    """三态路径决策（审计 §5.2）。

    黑名单只拦「已知的坏地方」，白名单才是「确定安全的地方」——两者的差集必须由用户拍板，
    不能再默默放行（原来读任意用户目录是静默允许的）。
    """
    ok, msg, resolved = check_path(path, for_write=for_write)
    if not ok or resolved is None:
        return PathDecision.DENY, msg, None
    norm = _norm(resolved)
    for blocked in _CREDENTIAL_DIRS:
        if _under(norm, blocked):
            return (PathDecision.DENY,
                    f"[error] 凭据/密钥目录不可访问: {resolved}（含 cookie、凭据库或私钥）", None)
    for root in _allowed_roots(workspace):
        if _under(norm, root):
            return PathDecision.ALLOW, "", resolved
    return (PathDecision.CONFIRM,
            f"路径在 workspace 之外：{resolved}", resolved)


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
