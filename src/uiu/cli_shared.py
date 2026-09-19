"""各域共用的 CLI 工具函数（工作区解析、输出、确认、会话上限）（自原 commands.py 按域拆分；审计 §2.1）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths, tools
from .config import (
    AppConfig,
    ChannelConfig,
    ModelConfig,
    config_yaml_path,
    ensure_workspace,
    load_config,
    parse_env_file,
    save_config,
    write_env_file,
)
from .workspace import load_workspace


# ---------- helpers ----------


def _workspace(args) -> Path:
    ws_arg = getattr(args, "workspace", None) or os.environ.get("UIU_WORKSPACE")
    if ws_arg:
        return Path(ws_arg).expanduser()
    # Default resolution: existing workspace > home (~/.uiu/workspace)
    # Home-priority fallback: no local workspace -> use the personal dir
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", paths.home_workspace()):
        if (cand / "config.yaml").exists() or (cand / "SOUL.md").exists() or cand.is_dir():
            return cand
    return paths.home_workspace()


def _print_ok(msg: str) -> None:
    print(f"[ok] {msg}")


def _print_err(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr)


def _confirm_or_abort(prompt: str, yes: bool, *, action: str) -> bool | None:
    """确认三态：True=继续执行，False=用户明确拒绝，None=**非交互环境无法确认**。

    None 时调用方必须返回非 0。破坏性操作在脚本/CI 里「什么都没做却报成功」是最危险的反馈：
    实测 `uiu restore` 在管道里会自动取消，却返回 0 —— `uiu restore b.zip && echo OK`
    会打印 OK 而实际什么都没恢复。
    """
    if yes:
        return True
    try:
        if not sys.stdin.isatty():
            _print_err(f"{action} 需要确认，但当前不是交互终端。请显式加 --yes 后重试。")
            return None
    except Exception:
        pass
    # 不能只信 isatty()：实测在管道/CI 里它可能谎报 True，而 input() 立刻拿到 EOF。
    # 所以把「读不到答案」也当成无法确认（而不是当成用户拒绝）。
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        _print_err(f"{action} 需要确认，但读不到输入（管道/CI？）。请显式加 --yes 后重试。")
        return None
    if not ans:
        return False
    return ans in ("y", "yes")


def _confirm(prompt: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes")


def _session_cap(ws) -> int:
    """会话数量上限（配置里 sessions_keep；<=0 表示不限）。"""
    try:
        return int(getattr(load_config(ws), "sessions_keep", 200) or 0)
    except Exception:
        return 200


def _session_age_days(ws) -> float:
    try:
        return float(getattr(load_config(ws), "sessions_max_age_days", 0.0) or 0.0)
    except Exception:
        return 0.0


def _is_git_source_install() -> bool:
    """True when running from a git checkout (dev mode). PyPI/npm installs aren't."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    return (repo_root / ".git").exists() or (repo_root / "src").is_dir()


def _plugins_dir() -> Path:
    return paths.providers_plugins_dir()
