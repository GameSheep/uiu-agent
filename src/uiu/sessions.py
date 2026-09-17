"""会话持久化 / resume / 压缩 / 跨会话检索：workspace/sessions/<id>.json。

- save/load/list/remove：TUI /save /resume /sessions、网关落盘共用
- compact：超预算时先 LLM 摘要旧轮（无 client 时纯截断兜底），system 恒保留
- search_sessions：Hermes session_search 的 stdlib 版——纯关键词跨会话检索，
  返回命中轮 ± 上下文（bookend 思路），零依赖零 token
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from ._atomic import atomic_write_json, file_lock, load_json_tolerant


def sessions_dir(workspace: Path) -> Path:
    d = Path(workspace) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(workspace: Path, sid: str) -> Path:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_").strip("-_")[:64] or "default"
    return sessions_dir(workspace) / f"{safe}.json"


def save_session(workspace: Path, sid: str, messages: list[dict]) -> str:
    p = _path(workspace, sid)
    payload = {"id": p.stem, "updated": time.time(), "messages": messages}
    # 原子写 + 加锁：TUI / gateway / daemon 可能同时保存同一个会话
    with file_lock(p):
        atomic_write_json(p, payload)
    return str(p)


def load_session(workspace: Path, sid: str) -> list[dict] | None:
    p = _path(workspace, sid)
    if not p.exists():
        return None
    data = load_json_tolerant(p, None)      # 损坏文件会先备份再当空处理
    if not isinstance(data, dict):
        return None
    msgs = data.get("messages")
    return msgs if isinstance(msgs, list) else None


def list_sessions(workspace: Path) -> list[dict]:
    out = []
    d = sessions_dir(workspace)
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        data = load_json_tolerant(p, None)
        if not isinstance(data, dict):
            continue
        msgs = data.get("messages", [])
        out.append({"id": p.stem, "updated": data.get("updated", 0),
                    "turns": sum(1 for m in msgs if m.get("role") == "user")})
    return out


def recent_sessions(workspace: Path, limit: int = 8) -> list[dict]:
    """Cheap listing (id + mtime only, no JSON parse) for live UI surfaces."""
    out: list[dict] = []
    try:
        d = sessions_dir(workspace)
        files = sorted(d.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except Exception:
        return out
    for p in files:
        try:
            out.append({"id": p.stem, "updated": p.stat().st_mtime})
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


# ---------- cross-session search (Hermes session_search, stdlib-only) ----------


def _session_index(messages: list[dict]) -> str:
    """Lowercased searchable text for one session (user+assistant turns only)."""
    parts = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        c = m.get("content")
        if isinstance(c, str):
            parts.append(c.lower())
        elif isinstance(c, list):  # anthropic tool_result blocks
            for b in c:
                if isinstance(b, dict) and isinstance(b.get("content"), str):
                    parts.append(b["content"].lower())
    return "\n".join(parts)


def search_sessions(workspace: Path, query: str, limit: int = 5) -> list[dict]:
    """Keyword search across saved sessions (no LLM, ~ms). Returns excerpts.

    Query words are space-separated and AND-matched (lowercased substring).
    Each hit: {session, role, text, context:[{role,text}...]} — the best
    matching turn plus one turn before/after as context (bookend framing).
    """
    terms = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
    if not terms:
        return []
    out: list[dict] = []
    d = sessions_dir(workspace)
    for p in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if len(out) >= limit:
            break
        try:
            msgs = json.loads(p.read_text(encoding="utf-8")).get("messages", [])
        except Exception:
            continue
        idx = _session_index(msgs)
        if not all(t in idx for t in terms):
            continue
        # pick the session's best-matching turn (most term hits)
        best = None  # (score, index)
        for i, m in enumerate(msgs):
            c = m.get("content")
            if not isinstance(c, str) or m.get("role") not in ("user", "assistant"):
                continue
            cl = c.lower()
            score = sum(cl.count(t) for t in terms)
            if score and (best is None or score > best[0]):
                best = (score, i)
        if best is None:
            continue
        i = best[1]
        c = msgs[i]["content"]
        excerpt = c[:500] if len(c) <= 500 else c[:250] + "…" + c[-250:]
        lo, hi = max(0, i - 1), min(len(msgs), i + 2)
        out.append({
            "session": p.stem,
            "role": msgs[i]["role"],
            "text": excerpt,
            "context": [{"role": msgs[j].get("role", "?"),
                         "text": (msgs[j].get("content") or "")[:300]}
                        for j in range(lo, hi)
                        if j != i
                        and msgs[j].get("role") in ("user", "assistant")
                        and isinstance(msgs[j].get("content"), str)],
        })
    return out[:limit]


def format_search_results(hits: list[dict]) -> str:
    """Render search results as compact text for the agent/tool result."""
    if not hits:
        return "(no matches in saved sessions)"
    lines = []
    for h in hits:
        head = f"[{h['session']} · {h['role']}] {h['text']}"
        lines.append(head[:600])
        for c in h.get("context", []):
            lines.append(f"    · ({c['role']}) {c['text'][:200]}")
    return "\n".join(lines)


SESSION_SEARCH_DEF = {
    "type": "function",
    "function": {
        "name": "session_search",
        "description": "在已保存的会话记录里做关键词检索（免费、秒回）。当用户说“我们上次聊过/之前说过 X”或你记不清是否处理过某主题时使用。返回命中片段及上下文。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词，如 '部署 服务器'"},
                "limit": {"type": "integer", "description": "最多返回几条（默认 5）"},
            },
            "required": ["query"],
        },
    },
}


def session_search_tool(query: str, limit: int = 5) -> str:
    """Tool body: search the active workspace's saved sessions."""
    from .workspace import find_workspace
    ws = find_workspace()
    if not ws:
        return "(no workspace)"
    try:
        hits = search_sessions(ws, query, limit=max(1, min(int(limit or 5), 10)))
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"
    return format_search_results(hits)
