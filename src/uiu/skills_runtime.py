"""Skill executor: simple built-in dispatch for skills.

Phase-1 skill model: a skill can declare an `exec:` line in its SKILL.md that
maps to a builtin function. Examples:

    exec: echo

This keeps the skeleton tiny while still letting users define skills without
writing Python. If no `exec:` is declared, the agent sees the skill body as
guidance text (read-on-demand) but cannot call it as a tool.
"""

from __future__ import annotations

import re
from typing import Callable

from .workspace import Skill

# simple builtin dispatch table for skill `exec:` declarations
SKILL_EXEC: dict[str, Callable[..., str]] = {}


def register(name: str, fn: Callable[..., str]) -> None:
    SKILL_EXEC[name] = fn


def find_exec(skill: Skill) -> str | None:
    m = re.search(r"^exec:\s*(\S+)\s*$", skill.body, re.MULTILINE)
    return m.group(1) if m else None


def try_execute(skill: Skill, arguments_json: str) -> str | None:
    """Try to run a skill by its declared `exec:` builtin. Returns None if not callable."""
    target = find_exec(skill)
    if not target:
        return None
    fn = SKILL_EXEC.get(target)
    if not fn:
        return f"[error] skill '{skill.name}' declares exec='{target}' but no such builtin is registered"
    import json
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return f"[error] skill args must be JSON object, got {type(args).__name__}"
        return fn(**args)
    except json.JSONDecodeError as e:
        return f"[error] invalid JSON args: {e}"
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ---------- builtins ----------

def _builtin_echo(input: str) -> str:
    return input


def _builtin_say_hello(input: str) -> str:
    """Greet with a bit of flair. The 'input' is a person or occasion."""
    return f"👋 你好，{input}！"


register("echo", _builtin_echo)
register("say_hello", _builtin_say_hello)


# ---------- progressive disclosure (Hermes skills_list/skill_view) ----------

def _current_skills():
    """Stateless: reload index from disk so list/view never go stale."""
    from .workspace import find_workspace, load_workspace
    try:
        return load_workspace(find_workspace()).skills
    except Exception:
        return []


def skills_list() -> str:
    """List skill index (names + one-line descriptions only)."""
    skills = _current_skills()
    if not skills:
        return "(no skills — add SKILL.md under workspace/skills/<name>/)"
    return "\n".join(f"- {s.name}: {s.description[:160]}" for s in skills)


def skill_view(name: str) -> str:
    """Read one skill's full SKILL.md body on demand."""
    name = (name or "").strip()
    if not name:
        return "[error] name 不能为空"
    for s in _current_skills():
        if s.name == name:
            body = s.body or ""
            if len(body) > 12000:
                body = body[:12000] + "\n…（已截断）"
            return f"# skill/{s.name}\n{s.description}\n\n{body}"
    return f"[error] 未知 skill: {name}（用 skills_list 看索引）"


SKILLS_LIST_DEF = {
    "type": "function",
    "function": {
        "name": "skills_list",
        "description": "列出 skill 索引（仅名字+一句话）。需要某个 skill 的完整用法时再 skill_view 取全文。",
        "parameters": {"type": "object", "properties": {}},
    },
}

SKILL_VIEW_DEF = {
    "type": "function",
    "function": {
        "name": "skill_view",
        "description": "按需读取一个 skill 的完整 SKILL.md 全文。",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "skill 名"}},
            "required": ["name"],
        },
    },
}

SKILL_INDEX_TOOLS: dict[str, dict] = {
    "skills_list": {"def": SKILLS_LIST_DEF, "fn": skills_list},
    "skill_view": {"def": SKILL_VIEW_DEF, "fn": skill_view},
}


def skill_index_tool_defs() -> list[dict]:
    return [t["def"] for t in SKILL_INDEX_TOOLS.values()]