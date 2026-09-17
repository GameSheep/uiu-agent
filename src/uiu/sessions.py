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
from .schema import migrate, stamp


def sessions_dir(workspace: Path) -> Path:
    d = Path(workspace) / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(workspace: Path, sid: str) -> Path:
    safe = "".join(c for c in sid if c.isalnum() or c in "-_").strip("-_")[:64] or "default"
    return sessions_dir(workspace) / f"{safe}.json"


def save_session(workspace: Path, sid: str, messages: list[dict]) -> str:
    p = _path(workspace, sid)
    payload = stamp("session", {"id": p.stem, "updated": time.time(), "messages": messages})
    # 原子写 + 加锁：TUI / gateway / daemon 可能同时保存同一个会话
    with file_lock(p):
        atomic_write_json(p, payload)
    return str(p)


def load_session(workspace: Path, sid: str) -> list[dict] | None:
    p = _path(workspace, sid)
    if not p.exists():
        return None
    data = load_json_tolerant(p, None)      # 损坏文件会先备份再当空处理
    if data is None:
        return None
    data, _ = migrate("session", data)      # 老格式在读时透明升级
    if not isinstance(data, dict):
        return None
    msgs = data.get("messages")
    return msgs if isinstance(msgs, list) else None


def list_sessions(workspace: Path) -> list[dict]:
    """按语义时间（JSON 里的 updated）倒序列出会话。

    不能用文件 mtime：备份/恢复、手工 touch、杀软扫描都会改 mtime，
    会让「最新的 N 个」变成随机结果（prune/keep 直接受影响）。
    老会话没有 updated 字段时才退回 mtime。
    """
    out = []
    d = sessions_dir(workspace)
    for p in d.glob("*.json"):
        data = load_json_tolerant(p, None)
        if data is None:
            continue
        data, _ = migrate("session", data)
        if not isinstance(data, dict):
            continue
        msgs = data.get("messages", [])
        try:
            stat = p.stat()
        except OSError:
            continue
        updated = data.get("updated", 0) or stat.st_mtime
        out.append({"id": p.stem, "updated": updated, "bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                    "turns": sum(1 for m in msgs if m.get("role") == "user")})
    out.sort(key=lambda r: r["updated"], reverse=True)
    return out


def sessions_usage(workspace: Path) -> dict:
    """占用概览：会话数、总字节、最旧/最新（给 /sessions、TUI 与 doctor 用）。"""
    rows = list_sessions(workspace)          # 已按 updated/mtime 倒序
    return {
        "count": len(rows),
        "bytes": sum(r.get("bytes", 0) for r in rows),
        "largest": sorted(rows, key=lambda r: r.get("bytes", 0), reverse=True)[:5],
        "newest": rows[0]["id"] if rows else "",
        "oldest": rows[-1]["id"] if rows else "",
        "sessions": rows,
    }


def prune_sessions(workspace: Path, *, keep: int = 200, max_age_days: float = 0.0,
                   protect: tuple[str, ...] = (), dry_run: bool = False) -> dict:
    """按数量/天数裁剪旧会话。

    删除是**可撤销**的：走回收站（uiu trash 可恢复）。
    规则：同时满足「不在最新 keep 个之内」且「超过 max_age_days 天」才会被裁；
    只给其中一个条件时按该条件裁剪；protect 里的 id 永不裁。
    """
    usage = sessions_usage(workspace)
    rows = usage["sessions"]
    protected = {str(x) for x in protect}
    cutoff = (time.time() - float(max_age_days) * 86400
              if max_age_days and max_age_days > 0 else None)
    use_keep = bool(keep and keep > 0)

    victims: list[dict] = []
    for idx, row in enumerate(rows):
        if row["id"] in protected:
            continue
        too_many = use_keep and idx >= keep
        too_old = cutoff is not None and row.get("updated", 0) < cutoff
        if use_keep and cutoff is not None:
            if too_many and too_old:
                victims.append(row)
        elif too_many or too_old:
            victims.append(row)

    removed: list[str] = []
    if not dry_run:
        for row in victims:
            if remove_session_ex(workspace, row["id"]) is not None:
                removed.append(row["id"])
    else:
        removed = [r["id"] for r in victims]

    return {"removed": removed, "kept": len(rows) - len(victims),
            "freed": sum(r.get("bytes", 0) for r in victims),
            "dry_run": bool(dry_run)}


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


def remove_session_ex(workspace: Path, sid: str, *, hard: bool = False) -> dict | None:
    """删除会话，返回回收站条目（hard=True 时直接删并返回 {"id": "hard"}）。"""
    path = _path(workspace, sid)
    if not path.exists():
        return None
    if hard:
        try:
            path.unlink()
            return {"id": "hard"}
        except OSError:
            return None
    try:
        from .trash import add_file
        return add_file(workspace, path, kind="session", label=sid)
    except Exception:
        return None                 # 回收站写不进去时保留文件，不静默丢


def remove_session(workspace: Path, sid: str, *, hard: bool = False) -> bool:
    """删除会话。默认**移入回收站**（可 uiu trash --restore 找回），hard=True 才真删。"""
    return remove_session_ex(workspace, sid, hard=hard) is not None


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
