"""Episodic Experience Memory & Macro Recall — Letta (MemGPT) / Hermes Pattern.

Indexes successful execution trajectories and compiled macros.
Enables zero-thinking instant reuse: when a similar goal is requested,
it recalls the exact macro or trajectory and bypasses multi-turn LLM reasoning entirely.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
from typing import Any


def _get_episodic_file() -> Path:
    from .workspace import Workspace
    from .learning import _ws
    ws = _ws()
    root = ws.root if ws else Path.cwd()
    return root / "episodic_memory.json"


def _load_store() -> list[dict[str, Any]]:
    p = _get_episodic_file()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_store(episodes: list[dict[str, Any]]) -> None:
    p = _get_episodic_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_keywords(text: str) -> list[str]:
    # Extract alphanumeric and CJK word segments
    tokens = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9_-]{2,}", text.lower())
    stop_words = {"打开", "然后", "帮我", "请问", "一下", "这个", "那个", "修改", "操作"}
    return [t for t in tokens if t not in stop_words]


def record_episode(
    goal: str,
    target_app: str,
    macro_name: str,
    parameters: list[str] | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Store or update a verified execution episode with its compiled macro."""
    store = _load_store()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    auto_kws = keywords or _extract_keywords(f"{goal} {target_app}")

    existing = next((ep for ep in store if ep.get("macro_name") == macro_name), None)
    if existing:
        existing["success_count"] = existing.get("success_count", 1) + 1
        existing["last_run"] = now_str
        existing["goal"] = goal
        existing["keywords"] = list(set(existing.get("keywords", []) + auto_kws))
        if parameters is not None:
            existing["parameters"] = parameters
        _save_store(store)
        return existing

    new_ep = {
        "id": f"ep_{int(time.time())}_{len(store)+1}",
        "goal": goal.strip(),
        "target_app": target_app.strip(),
        "macro_name": macro_name.strip(),
        "parameters": parameters or [],
        "keywords": auto_kws,
        "success_count": 1,
        "created_at": now_str,
        "last_run": now_str,
    }
    store.append(new_ep)
    _save_store(store)
    return new_ep


def find_matching_macro(query: str, min_score: float = 0.45) -> dict[str, Any] | None:
    """Find the best matching compiled macro from episodic memory for zero-thinking replay."""
    store = _load_store()
    if not store:
        return None

    query_clean = query.lower().strip()
    query_tokens = set(_extract_keywords(query_clean))

    scored = []
    for ep in store:
        goal_text = ep.get("goal", "").lower()
        kws = set(ep.get("keywords", []))
        app = ep.get("target_app", "").lower()

        # 1. Token overlap
        overlap = len(query_tokens.intersection(kws))
        token_score = (overlap / max(1, len(kws))) if kws else 0.0

        # 2. String similarity
        seq_score = difflib.SequenceMatcher(None, query_clean, goal_text).ratio()

        # 3. Target app bonus
        app_bonus = 0.25 if (app and app in query_clean) else 0.0

        total_score = 0.5 * token_score + 0.35 * seq_score + app_bonus
        if total_score >= min_score:
            scored.append((total_score, ep))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_ep = scored[0]
    result = dict(best_ep)
    result["match_score"] = round(best_score, 3)
    return result


def list_episodes() -> list[dict[str, Any]]:
    """List all recorded episodic experiences."""
    return _load_store()
