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