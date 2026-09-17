"""Append-only 审计日志（审计 §5.6）。

工具执行（尤其是 shell / 文件写 / 发消息）此前没有任何持久记录，出事后无法追溯「谁在什么时候
用什么参数做了什么、用户是否确认过」。

- 落盘：<workspace>/audit/uiu-audit.jsonl（每行一个 JSON 事件）
- 追加写，加锁 + fsync；超过 max_bytes 滚动成 uiu-audit-<ts>.jsonl
- 参数里的密钥类字段会被脱敏（key/token/secret/password）
- 记录失败绝不影响工具执行本身
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

__all__ = ["audit_dir", "audit_path", "record", "read_events", "redact"]

MAX_BYTES = 5 * 1024 * 1024
_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "credential", "cookie")


def audit_dir(workspace: Path | str) -> Path:
    return Path(workspace) / "audit"


def audit_path(workspace: Path | str) -> Path:
    return audit_dir(workspace) / "uiu-audit.jsonl"


def redact(value: Any) -> Any:
    """把疑似密钥的字段值换成 ***（审计日志要能安全地给人看）。"""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(hint in str(k).lower() for hint in _SECRET_HINTS):
                out[k] = "***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _current_workspace() -> Path | None:
    import os
    ws = os.environ.get("UIU_WORKSPACE", "").strip()
    return Path(ws) if ws else None


def record(workspace: Path | str | None, event: str, **fields: Any) -> Path | None:
    """追加一条审计事件；返回写入的文件（失败时返回 None，绝不抛给调用方）。"""
    ws = Path(workspace) if workspace else _current_workspace()
    if ws is None:
        return None
    try:
        from ._atomic import file_lock
        from .log import get_logger

        target = audit_path(ws)
        payload = {"ts": round(time.time(), 3), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "event": event, **redact(fields)}
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        target.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(target):
            if target.exists() and target.stat().st_size > MAX_BYTES:
                target.replace(target.with_name(f"uiu-audit-{int(time.time())}.jsonl"))
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                try:
                    import os as _os
                    _os.fsync(fh.fileno())
                except OSError:
                    pass
        return target
    except Exception as exc:            # 审计失败不能拖垮工具执行
        try:
            from .log import get_logger
            get_logger("audit").warning("审计写入失败: %s", exc)
        except Exception:
            pass
        return None


def read_events(workspace: Path | str, *, tail: int = 50) -> list[dict]:
    """读取最近的审计事件（新→旧文件顺序，取末尾 tail 条）。"""
    d = audit_dir(workspace)
    if not d.is_dir():
        return []
    files = sorted(d.glob("uiu-audit*.jsonl"), key=lambda p: p.stat().st_mtime)
    events: list[dict] = []
    for path in files:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    return events[-tail:] if tail > 0 else events
