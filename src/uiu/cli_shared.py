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
