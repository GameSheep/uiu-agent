"""Usage-aware suggestions — Hermes /suggestions usage-source, minimal edition.

Hermes 后台会「注意到重复出现的请求」并建议自动化，由用户在 /suggestions 里
accept/dismiss，绝不自动创建。uiu 版本只做确定性计数（零 LLM、零后台线程）：

- 宏回放次数记录到 workspace/usage.json（宏文件保持纯净可分享）
- 回放 ≥3 次的宏 → 建议设成 cron 定时自动跑（宏→自动化闭环）
- 会话里重复出现的请求主题（词频，排除停用词）→ 建议沉淀成宏/skill
- /suggestions list/accept/dismiss；dismiss 记 latched 不再提示
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path

# 建议宏→cron 的回放次数阈值
MACRO_CRON_THRESHOLD = 3
# 请求重复主题的最小出现次数
TOPIC_MIN_COUNT = 3
# 排除的常见请求词（中文 bigram/词 + 英文虚词）
_STOP_WORDS = {
    # 中文常见词/语气
    "帮我", "请", "一下", "这个", "那个", "什么", "怎么", "如何", "为什么", "可以", "能", "要",
    "一个", "还有", "就是", "知道", "需要", "我想", "请问", "现在", "然后", "但是", "如果",
    "没有", "不是", "这样", "那样", "谢谢", "可以", "吗", "呢", "吧", "了", "的", "是", "在",
    # 英文虚词
    "the", "a", "an", "to", "of", "in", "on", "for", "with", "and", "or", "is", "are",
    "do", "does", "i", "you", "me", "my", "your", "it", "we", "please", "can", "how",
}


def _ws_root() -> Path | None:
    """Locate active workspace (same resolution as learning._ws)."""
    import os
    env = os.environ.get("UIU_WORKSPACE")
    if env:
        return Path(env).expanduser()
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", Path.home() / ".uiu" / "workspace"):
        if cand.is_dir():
            return cand
    return None


# ---------- usage recording ----------

def usage_path(root: Path) -> Path:
    return Path(root) / "usage.json"


def _load_usage(root: Path) -> dict:
    p = usage_path(root)
    if not p.exists():
        return {"macro_plays": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("macro_plays"), dict):
            return data
    except Exception:
        pass
    return {"macro_plays": {}}


def _save_usage(root: Path, data: dict) -> None:
    usage_path(root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_macro_play(root: Path, name: str) -> None:
    """Increment play count for a macro (called by macro_play on success)."""
    data = _load_usage(root)
    data["macro_plays"][name] = data["macro_plays"].get(name, 0) + 1
    _save_usage(root, data)


# ---------- suggestion state (accepted/dismissed latch) ----------

def _state_path(root: Path) -> Path:
    return Path(root) / "suggestions_state.json"


def _load_state(root: Path) -> dict:
    p = _state_path(root)
    if not p.exists():
        return {"accepted": [], "dismissed": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"accepted": [], "dismissed": []}


def _save_state(root: Path, data: dict) -> None:
    _state_path(root).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- scanning ----------

def _macro_candidates(root: Path) -> list[dict]:
    """Macros played >= threshold → suggest cron automation."""
    usage = _load_usage(root)
    d = Path(root) / "macros"
    out = []
    for name, count in usage.get("macro_plays", {}).items():
        if count < MACRO_CRON_THRESHOLD:
            continue
        # 宏还要真实存在
        p = d / f"{name}.json"
        if not p.exists():
            continue
        desc = ""
        try:
            desc = json.loads(p.read_text(encoding="utf-8")).get("description", "")
        except Exception:
            pass
        out.append({
            "id": f"macro-cron-{name}",
            "kind": "macro_cron",
            "title": f"宏 '{name}' 已回放 {count} 次",
            "detail": (desc or f"把常用宏 {name} 设成定时自动跑"),
            "action": "cron",
        })
    return out


# 会话里 user 消息的重复主题（CJK bigram + ASCII 词计数）
_ASCII_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def _topic_tokens(text: str) -> list[str]:
    """Tokenize into CJK bigrams (跨字捕获主题) + ascii words (len>=3)."""
    out: list[str] = []
    for w in _ASCII_RE.findall(text):
        if len(w) >= 3 and w not in _STOP_WORDS:
            out.append(w)
    for run in _CJK_RE.findall(text):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if bg not in _STOP_WORDS:
                out.append(bg)
    return out


def _session_topics(root: Path, min_count: int = TOPIC_MIN_COUNT) -> list[dict]:
    """Count repeated words/bigrams across saved user turns (exclude stop words)."""
    from .sessions import sessions_dir
    counter: Counter = Counter()
    for p in sessions_dir(root).glob("*.json"):
        try:
            msgs = json.loads(p.read_text(encoding="utf-8")).get("messages", [])
        except Exception:
            continue
        for m in msgs:
            if m.get("role") != "user" or not isinstance(m.get("content"), str):
                continue
            text = m["content"].lower()
            # 去掉 slash 命令
            if text.startswith("/"):
                continue
            for tok in _topic_tokens(text):
                if tok in _STOP_WORDS:
                    continue
                counter[tok] += 1
    out = []
    for tok, count in counter.most_common(8):
        if count < min_count:
            break
        out.append({
            "id": f"topic-{tok}",
            "kind": "topic",
            "title": f"「{tok}」相关请求出现 {count} 次",
            "detail": f"这个需求常出现，可考虑沉淀成宏或 skill 一键复用",
            "action": "skill_or_macro",
        })
    return out


def scan_suggestions(root: Path) -> list[dict]:
    """All pending suggestions (macro→cron + repeated topics), minus latched."""
    state = _load_state(root)
    latched = set(state.get("accepted", [])) | set(state.get("dismissed", []))
    cands = _macro_candidates(root) + _session_topics(root)
    return [c for c in cands if c["id"] not in latched]


# ---------- accept / dismiss ----------

def accept_suggestion(root: Path, sug_id: str) -> str:
    """Accept a suggestion. macro_cron → create cron job; returns message."""
    state = _load_state(root)
    if sug_id in state.get("accepted", []):
        return f"(建议 {sug_id} 已接受过)"
    if sug_id.startswith("macro-cron-"):
        name = sug_id[len("macro-cron-"):]
        from . import cron as _cron
        try:
            # 默认每天跑一次；schedule 可由后续 /suggestions 调整
            job = _cron.add_job(root, f"macro-{name}", "1d", f"用 macro_play 回放宏 {name}")
        except Exception as e:
            return f"[error] 创建 cron 失败: {e}"
        state.setdefault("accepted", []).append(sug_id)
        _save_state(root, state)
        return f"[ok] 已创建定时任务 '{job['name']}'（每天跑宏 {name}）— /cron list 查看"
    # topic 类建议：只做提示，接受即标记（不自动建 skill，避免质量差的自动沉淀）
    state.setdefault("accepted", []).append(sug_id)
    _save_state(root, state)
    return f"[ok] 已记录「{sug_id}」— 下次遇到可让 agent 沉淀成宏/skill"


def dismiss_suggestion(root: Path, sug_id: str) -> str:
    """Dismiss a suggestion (latched, never re-offered)."""
    state = _load_state(root)
    if sug_id not in state.get("dismissed", []):
        state.setdefault("dismissed", []).append(sug_id)
        _save_state(root, state)
    return f"(已忽略建议 {sug_id})"


def format_suggestions(items: list[dict]) -> str:
    if not items:
        return "(暂无建议 — 多用宏、多聊天，uiu 会发现重复并给出自动化建议)"
    lines = ["可用建议（/suggestions accept|dismiss <id>）"]
    for i, s in enumerate(items, 1):
        lines.append(f"  {i}. [{s['id']}] {s['title']}\n     {s['detail']}")
    return "\n".join(lines)
