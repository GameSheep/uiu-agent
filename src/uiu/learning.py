"""Self-learning — Hermes-aligned: agent persists knowledge & skills.

Hermes 的自学习核心是几个 agent 可调用的工具：
- memory:     agent 主动记/查/改长期记忆（memory_tool.py）
- skill_manager: agent 把成功方法沉淀成可复用 SKILL.md（skill_manager_tool.py）

uiu 版本：
- memory_add      -> 追加一条记忆到 MEMORY.md（带时间戳）
- memory_recall   -> 读 MEMORY.md / USER.md（跨会话知识）
- memory_replace  -> 替换/删除指定条目
- skill_create    -> 新建 workspace/skills/<name>/SKILL.md（沉淀方法）
- skill_improve   -> 改进已有 skill（追加 usage note / 修订）

这些注册为 built-in tools，agent 在对话中按需调用——即"自我学习"。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .workspace import Workspace


def _ws() -> Workspace | None:
    """Find the active workspace (env var > cwd/workspace)."""
    import os
    env = os.environ.get("UIU_WORKSPACE")
    if env:
        return Workspace(root=Path(env).expanduser())
    cwd_ws = Path.cwd() / "workspace"
    if cwd_ws.exists():
        return Workspace(root=cwd_ws)
    return None


def _memory_path() -> Path:
    ws = _ws()
    root = ws.root if ws else Path.cwd()
    return root / "MEMORY.md"


# ---------- memory ----------

def memory_add(content: str, target: str = "MEMORY.md") -> str:
    """Append a timestamped memory entry (Hermes memory action=add)."""
    path = _memory_path()
    if target.lower() not in ("memory.md", "memory", "facts"):
        target = "MEMORY.md"
    path = path.parent / target if "/" not in target else path
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d")
    line = f"- [{ts}] {content.strip()}"
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return f"[ok] 已记住: {content.strip()[:60]}"


def memory_recall() -> str:
    """Read back stored memory (Hermes memory recall)."""
    path = _memory_path()
    if not path.exists():
        return "(暂无记忆)"
    text = path.read_text(encoding="utf-8")
    return text.strip() or "(暂无记忆)"


def memory_replace(old: str, new: str) -> str:
    """Replace an existing memory entry (Hermes memory action=replace)."""
    path = _memory_path()
    if not path.exists():
        return "[error] 无记忆文件"
    text = path.read_text(encoding="utf-8")
    if old not in text:
        return f"[error] 未找到包含 '{old[:40]}' 的条目"
    updated = text.replace(old, new)
    path.write_text(updated, encoding="utf-8")
    return f"[ok] 已更新记忆"


def memory_remove(content: str) -> str:
    """Remove a memory entry containing the given substring (Hermes action=remove)."""
    path = _memory_path()
    if not path.exists():
        return "[error] 无记忆文件"
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [l for l in lines if content not in l]
    if len(kept) == len(lines):
        return f"[error] 未找到包含 '{content[:40]}' 的条目"
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return f"[ok] 已删除相关记忆"


# ---------- skills ----------

def _skills_dir() -> Path:
    ws = _ws()
    root = ws.root if ws else Path.cwd()
    return root / "skills"


def skill_create(name: str, description: str, instructions: str = "") -> str:
    """Create a reusable skill from a successful approach (Hermes skill_manager create).

    Writes workspace/skills/<name>/SKILL.md. The agent supplies the name,
    one-line description, and the procedural instructions it learned.
    """
    import re as _re
    safe = _re.sub(r"[^a-z0-9_-]", "_", name.lower()).strip("_")
    if not safe:
        return "[error] 无效技能名"
    skills_dir = _skills_dir()
    target = skills_dir / safe
    if target.exists():
        return f"[error] 技能已存在: {safe}（用 skill_improve 改进）"
    target.mkdir(parents=True, exist_ok=True)
    desc = description.strip() or f"{safe} — 从实践中沉淀的技能"
    body = (
        f"---\nname: {safe}\ndescription: {desc}\n---\n\n"
        f"# {safe}\n\n"
        f"## 何时使用\n{desc}\n\n"
        f"## 做法\n{instructions.strip()}\n\n"
        f"exec: \n"
    )
    (target / "SKILL.md").write_text(body, encoding="utf-8")
    return f"[ok] 已创建技能 {safe}（SKILL.md 已写入）"


def skill_improve(name: str, note: str = "") -> str:
    """Improve an existing skill by appending a usage note (Hermes self-improve)."""
    skills_dir = _skills_dir()
    target = skills_dir / name / "SKILL.md"
    if not target.exists():
        # try fuzzy match
        for d in skills_dir.iterdir():
            if d.is_dir() and name.lower() in d.name.lower():
                target = d / "SKILL.md"
                break
    if not target.exists():
        return f"[error] 技能不存在: {name}"
    text = target.read_text(encoding="utf-8")
    ts = time.strftime("%Y-%m-%d")
    note_line = f"- [{ts}] {note.strip()}" if note.strip() else f"- [{ts}] (使用改进)"
    if "## 使用记录" not in text:
        text += f"\n## 使用记录\n{note_line}\n"
    else:
        text = text.replace("## 使用记录", f"## 使用记录\n{note_line}", 1)
    target.write_text(text, encoding="utf-8")
    return f"[ok] 已改进技能 {name}"


# ---------- tool definitions (OpenAI function schema) ----------

MEMORY_ADD_DEF = {
    "type": "function",
    "function": {
        "name": "memory_add",
        "description": "把值得长期记住的事实追加到记忆库（如用户偏好、项目背景、常用命令）。自动带时间戳。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要记住的内容，一句话"},
            },
            "required": ["content"],
        },
    },
}

MEMORY_RECALL_DEF = {
    "type": "function",
    "function": {
        "name": "memory_recall",
        "description": "读取已存储的长期记忆（关于用户、项目、偏好的事实）。",
        "parameters": {"type": "object", "properties": {}},
    },
}

MEMORY_REPLACE_DEF = {
    "type": "function",
    "function": {
        "name": "memory_replace",
        "description": "更新一条已有的记忆（先 memory_recall 找到原文）。",
        "parameters": {
            "type": "object",
            "properties": {
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["old", "new"],
        },
    },
}

SKILL_CREATE_DEF = {
    "type": "function",
    "function": {
        "name": "skill_create",
        "description": "把一次成功的问题解决方法沉淀成可复用技能（写入 SKILL.md）。当用户重复做类似的事、或你发现一个可复用流程时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "技能名（小写+下划线）"},
                "description": {"type": "string", "description": "一句话：何时用这个技能"},
                "instructions": {"type": "string", "description": "具体做法步骤"},
            },
            "required": ["name", "description", "instructions"],
        },
    },
}

SKILL_IMPROVE_DEF = {
    "type": "function",
    "function": {
        "name": "skill_improve",
        "description": "改进已有技能：追加一条使用记录或修订。当发现之前沉淀的方法有更优做法时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "note": {"type": "string", "description": "这次的改进点/新发现"},
            },
            "required": ["name", "note"],
        },
    },
}


LEARNING_TOOLS: dict[str, dict] = {
    "memory_add": {"def": MEMORY_ADD_DEF, "fn": memory_add},
    "memory_recall": {"def": MEMORY_RECALL_DEF, "fn": memory_recall},
    "memory_replace": {"def": MEMORY_REPLACE_DEF, "fn": memory_replace},
    "skill_create": {"def": SKILL_CREATE_DEF, "fn": skill_create},
    "skill_improve": {"def": SKILL_IMPROVE_DEF, "fn": skill_improve},
}


def learning_tool_defs() -> list[dict]:
    return [t["def"] for t in LEARNING_TOOLS.values()]


def call_learning_tool(name: str, arguments_json: str) -> str:
    if name not in LEARNING_TOOLS:
        return f"[error] unknown learning tool: {name}"
    fn = LEARNING_TOOLS[name]["fn"]
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            return f"[error] args must be object"
        return fn(**args)
    except TypeError as e:
        return f"[error] bad arguments: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


# ---------- self-improve nudge (Hermes "periodic nudges") ----------

NUDGE_PROMPT = """\
（自学习）回顾刚才的对话，判断是否有值得沉淀的东西。如果有，调用相应工具：
- 用户透露了持久的偏好/事实 → memory_add
- 发现了一个可复用的解决流程 → skill_create
如果没什么可沉淀的，直接回复 "无需沉淀" 三个字，不要调用工具。
"""


def nudge_prompt() -> str:
    """Return the self-improve nudge prompt (injected every N turns)."""
    return NUDGE_PROMPT