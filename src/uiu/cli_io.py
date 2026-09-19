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


def configure_stdio() -> None:
    """把标准输出的**编码错误策略**改成 replace —— 一处兜底，全命令不再因编码崩。

    中文 Windows 控制台是 GBK，而文案里有 ⭐ / ✓ / ⚙ 这类不在 GBK 码表里的符号，
    print() 会抛 UnicodeEncodeError 把整条命令打挂（实测 uiu publish 与 uiu skills search 都死过）。
    改成 replace 后：中文照常显示，个别符号降级成 "?"，但命令一定跑得完。
    这比"逐个把符号换成 ASCII"牢靠——以后谁写新文案都不会再踩。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")     # type: ignore[union-attr]
        except Exception:                            # 非 TextIOWrapper（被重定向/被测试捕获）
            pass


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


def _safe_print(text: str, stream) -> None:
    """打印**永远不许**让命令崩掉。

    中文 Windows 的控制台编码是 GBK：像 `✓`（U+2713）这种符号不在 GBK 码表里，
    print() 会抛 UnicodeEncodeError。一个进度提示把 `uiu publish` 整条命令打挂，
    是实测发生过的（发布命令 4 秒就死在第一个人读提示上）。
    注意：pytest 捕获的是**文本**，所以单测看不出这个问题——必须有真控制台编码的用例。
    """
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        safe = text.encode(enc, errors="replace").decode(enc, errors="replace")
        print(safe, file=stream, flush=True)


def progress(message: str) -> None:
    """人读进度。JSON 模式下写 stderr，保证 stdout 干净。"""
    stream = sys.stderr if _JSON_MODE else sys.stdout
    _safe_print(message, stream)


def fail(message: str) -> None:
    _safe_print(f"[error] {message}", sys.stderr)


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
        _safe_print(json.dumps(_envelope(command, ok, data, error), ensure_ascii=False),
                    sys.stdout)
        return
    if human:
        stream = sys.stdout if ok else sys.stderr
        _safe_print(human, stream)


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
        progress(f"  [x] {name} 中断（{elapsed:.1f}s）")
        raise
    elapsed = time.monotonic() - started
    # 标记只用 ASCII：与 _print_ok/_print_err 的 [ok]/[x] 保持一致，
    # 也避免在 GBK 控制台上踩编码坑（✓/✗ 不在 GBK 里）
    mark = "[ok]" if state.get("ok", True) else "[x]"
    timing = f"（{elapsed:.1f}s）" if show_ms and elapsed >= 0.05 else ""
    detail = f" {state.get('detail')}" if state.get("detail") else ""
    progress(f"  {mark} {name}{timing}{detail}")
