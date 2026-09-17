"""CLI 输出约定：进度反馈 + `--json`（审计 §1.4 / §4.3）。

两条规矩：

1. **`--json` 时 stdout 只允许出现一个 JSON 文档**——人读信息（进度/提示）一律走 stderr，
   脚本可以放心 `uiu ... --json | jq`。
2. **长任务要给进度**：`step()` 打印开始提示与耗时；非 TTY 不打动画（日志里不留转义字符）。

统一信封：

    {"ok": true, "command": "sessions.list", "data": {...}}
    {"ok": false, "command": "trash.restore", "error": "没有这条记录"}
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator

__all__ = ["json_mode", "set_json_mode", "progress", "fail", "result", "step", "is_tty"]

_JSON_MODE = False


def is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def json_mode() -> bool:
    return _JSON_MODE


def set_json_mode(enabled: bool) -> None:
    global _JSON_MODE
    _JSON_MODE = bool(enabled)


def progress(message: str) -> None:
    """人读进度。JSON 模式下写 stderr，保证 stdout 干净。"""
    stream = sys.stderr if _JSON_MODE else sys.stdout
    print(message, file=stream, flush=True)


def fail(message: str) -> None:
    print(f"[error] {message}", file=sys.stderr, flush=True)


def _envelope(command: str, ok: bool, data: Any = None, error: str = "") -> dict:
    payload: dict[str, Any] = {"ok": bool(ok), "command": command}
    if data is not None:
        payload["data"] = data
    if error:
        payload["error"] = error
    return payload


def result(command: str, *, ok: bool = True, data: Any = None, error: str = "",
           human: str = "") -> None:
    """按当前模式输出：JSON 信封 or 人读文本。"""
    if _JSON_MODE:
        print(json.dumps(_envelope(command, ok, data, error), ensure_ascii=False))
        return
    if human:
        stream = sys.stdout if ok else sys.stderr
        print(human, file=stream)


@contextmanager
def step(name: str, *, show_ms: bool = True) -> Iterator[dict]:
    """包住一个长步骤：开始时给提示，结束时给结果与耗时。

    用法：
        with step("构建 wheel") as s:
            ...
            s["detail"] = "1.2 MB"
    """
    progress(f"· {name}…")
    started = time.monotonic()
    state: dict[str, Any] = {"ok": True, "detail": ""}
    try:
        yield state
    except BaseException:
        elapsed = time.monotonic() - started
        progress(f"  ✗ {name} 中断（{elapsed:.1f}s）")
        raise
    elapsed = time.monotonic() - started
    mark = "✓" if state.get("ok", True) else "✗"
    timing = f"（{elapsed:.1f}s）" if show_ms and elapsed >= 0.05 else ""
    detail = f" {state.get('detail')}" if state.get("detail") else ""
    progress(f"  {mark} {name}{timing}{detail}")
