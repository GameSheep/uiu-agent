"""会话持久化 / resume / 压缩：workspace/sessions/<id>.json。

- save/load/list/remove：TUI /save /resume /sessions、网关落盘共用
- compact：超预算时先 LLM 摘要旧轮（无 client 时纯截断兜底），system 恒保留
"""

from __future__ import annotations

import json
import time
from pathlib import Path


def sessions_dir(workspace: Path) -> Path:
    d = Path(workspace) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(workspace: Path, sid: str) -> Path:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_").strip("-_")[:64] or "default"
    return sessions_dir(workspace) / f"{safe}.json"


def save_session(workspace: Path, sid: str, messages: list[dict]) -> str:
    p = _path(workspace, sid)
    p.write_text(json.dumps({"id": p.stem, "updated": time.time(), "messages": messages},
                            ensure_ascii=False), encoding="utf-8")
    return str(p)


def load_session(workspace: Path, sid: str) -> list[dict] | None:
    p = _path(workspace, sid)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        msgs = data.get("messages")
        return msgs if isinstance(msgs, list) else None
    except Exception:
        return None


def list_sessions(workspace: Path) -> list[dict]:
    out = []
    d = sessions_dir(workspace)
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            msgs = data.get("messages", [])
            out.append({"id": p.stem, "updated": data.get("updated", 0),
                        "turns": sum(1 for m in msgs if m.get("role") == "user")})
        except Exception:
            continue
    return out


def remove_session(workspace: Path, sid: str) -> bool:
    try:
        _path(workspace, sid).unlink()
        return True
    except OSError:
        return False


def _chars(messages: list[dict]) -> int:
    return sum(len(m.get("content", "")) if isinstance(m.get("content"), str) else 400 for m in messages)


def context_chars(messages: list[dict] | None) -> int:
    """Public: total prompt chars (for status line / /usage)."""
    return _chars(messages or [])


def estimate_tokens(chars: int) -> int:
    """Rough token estimate (~4 chars/token mixed CJK+ASCII)."""
    return max(0, int(chars / 4))


def compact_messages(messages: list[dict], max_chars: int = 60_000, summarizer=None) -> list[dict]:
    """超预算时压缩：system 保留 + 旧轮摘要（或截断）+ 最近轮保留。"""
    if _chars(messages) <= max_chars or len(messages) <= 3:
        return messages
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    # 保留最近 ~1/3，旧的 2/3 摘要或丢弃
    keep_n = max(2, len(rest) // 3)
    old, recent = rest[:-keep_n], rest[-keep_n:]
    summary = ""
    if summarizer is not None:
        try:
            summary = summarizer(old) or ""
        except Exception:
            summary = ""
    if summary:
        return system + [{"role": "user",
                          "content": f"[此前 {len(old)} 轮对话摘要]\n{summary[:4000]}"}] + recent
    return system + recent
