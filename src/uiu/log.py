"""统一日志：分级 + 轮转 + workspace 落盘。

审计 §2.2 之前的状态：源码里 236 处 `print` 对 2 处 `logging`，没有 FileHandler，
daemon 手写 append 到 `~/.uiu/daemon.log`（无分级、无轮转、可能被撑爆）。

gateway / daemon 是长期驻留进程，出问题时必须能回溯，所以：

- 文件：`<workspace>/logs/uiu.log`，默认 5MB × 3 份轮转
- 级别：`UIU_LOG_LEVEL`（默认 INFO）
- 控制台：仅当 `UIU_LOG_CONSOLE=1` 时打到 stderr
  （TUI 有自己的界面输出，再往终端写日志只会互相盖）
- **日志失败绝不能让程序起不来**：目录建不出来就静默降级

用法：`log = get_logger("gateway")`；长期进程入口调一次 `setup_logging(workspace)`。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

ROOT_NAME = "uiu"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUPS = 3
_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def log_dir(workspace: Path | str) -> Path:
    return Path(workspace) / "logs"


def log_path(workspace: Path | str) -> Path:
    return log_dir(workspace) / "uiu.log"


def _resolve_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    name = str(level or os.environ.get("UIU_LOG_LEVEL") or "INFO").upper()
    return getattr(logging, name, logging.INFO) if isinstance(getattr(logging, name, None), int) else logging.INFO


def setup_logging(workspace: Path | str | None = None, *,
                  level: str | int | None = None,
                  console: bool | None = None,
                  max_bytes: int | None = None,
                  backups: int | None = None) -> logging.Logger:
    """Attach (once per file) a rotating file handler; safe to call anywhere."""
    root = logging.getLogger(ROOT_NAME)
    root.setLevel(_resolve_level(level))
    root.propagate = False          # 我们自己管 handler，别被外部 root 配置重复打印

    if workspace is not None:
        target = log_path(workspace)
        attached: set[str] = getattr(root, "_uiu_files", set())
        if str(target) not in attached:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                handler: logging.Handler = RotatingFileHandler(
                    target,
                    maxBytes=int(max_bytes or os.environ.get("UIU_LOG_MAX_BYTES") or DEFAULT_MAX_BYTES),
                    backupCount=int(backups if backups is not None
                                   else os.environ.get("UIU_LOG_BACKUPS") or DEFAULT_BACKUPS),
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
                root.addHandler(handler)
                attached = set(attached) | {str(target)}
                root._uiu_files = attached                     # type: ignore[attr-defined]
            except Exception:
                pass        # 日志失败不是崩溃理由

    want_console = console
    if want_console is None:
        want_console = os.environ.get("UIU_LOG_CONSOLE", "").strip().lower() in ("1", "true", "yes", "on")
    if want_console and not getattr(root, "_uiu_console", False):
        try:
            stream = logging.StreamHandler(sys.stderr)
            stream.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
            root.addHandler(stream)
            root._uiu_console = True                           # type: ignore[attr-defined]
        except Exception:
            pass
    return root


def get_logger(name: str = "") -> logging.Logger:
    """`get_logger("gateway")` → logger named `uiu.gateway`."""
    return logging.getLogger(f"{ROOT_NAME}.{name}" if name else ROOT_NAME)


def close_handlers() -> None:
    """Close and detach every handler we attached.

    Needed whenever a process is done with a workspace: on Windows an open log
    file keeps the directory locked, so e.g. deleting a scratch workspace fails
    until the handler is closed.
    """
    root = logging.getLogger(ROOT_NAME)
    for handler in list(root.handlers):
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)
    for attr in ("_uiu_files", "_uiu_console"):
        if hasattr(root, attr):
            delattr(root, attr)


def reset_for_tests() -> None:
    """Alias kept for tests switching workspaces."""
    close_handlers()
