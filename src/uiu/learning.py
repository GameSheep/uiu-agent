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


# 记忆写入后回调：用于运行期热刷新（TUI/gateway 注册后，ws.memory 立即更新）
_memory_hooks: list = []


def register_memory_hook(fn) -> None:
    """Register a callable invoked after any memory write (best-effort refresh)."""
    if callable(fn) and fn not in _memory_hooks:
        _memory_hooks.append(fn)


def _notify_memory_changed() -> None:
    for fn in list(_memory_hooks):
        try:
            fn()
        except Exception:
            pass


def notify_memory_changed() -> None:
    """Public: ping registered hot-reload hooks after a memory write."""
    _notify_memory_changed()


def _ws() -> Workspace | None:
    """Find the active workspace (env > cwd/workspace > ~/workspace > ~/.uiu/workspace)."""
    import os
    env = os.environ.get("UIU_WORKSPACE")
    if env:
        return Workspace(root=Path(env).expanduser())
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", Path.home() / ".uiu" / "workspace"):
        if cand.is_dir():
            return Workspace(root=cand)
    return None


def _memory_path() -> Path:
    ws = _ws()
    root = ws.root if ws else Path.cwd()
    return root / "MEMORY.md"


# ---------- memory ----------

# Hermes 风格有界记忆：MEMORY.md 是一个「小预算」curated 文件，
# 超预算时拒绝写入并提示先合并 —— 逼 agent 自己 consolidate，而非无限膨胀。
MEMORY_BUDGET = 3000      # 记忆文件正文预算（字符）
MEMORY_WARN_AT = 0.8      # 超过 80% 即提示合并


def _memory_stats(path: Path) -> tuple[int, int, int]:
    """Count memory entries and usage. Returns (n_entries, used_chars, budget).

    Entries are top-level `- [` bullet lines (offset of the leading header is
    excluded from the used budget). used = chars of entry lines only.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    header_end = 0
    for i, ln in enumerate(lines):
        if ln.startswith("#"):
            header_end = i + 1
        elif ln.startswith("-"):
            break
    used = sum(len(ln) + 1 for ln in lines[header_end:] if ln.strip())
    n = sum(1 for ln in lines[header_end:] if ln.startswith("-"))
    return n, used, MEMORY_BUDGET


def memory_usage() -> str:
    """Usage meter for the system prompt (agent sees how full memory is)."""
    path = _memory_path()
    if not path.exists():
        return "（记忆 0%，空）"
    try:
        n, used, budget = _memory_stats(path)
    except OSError:
        return "（记忆文件不可读）"
    pct = min(999, int(used * 100 / budget))
    return f"（记忆 {pct}% · {used}/{budget} 字符 · {n} 条；超 80% 先 memory_replace 合并同类再新增）"


def memory_add(content: str, target: str = "MEMORY.md") -> str:
    """Append a timestamped memory entry (Hermes memory action=add).

    Enforces the MEMORY.md budget: once usage exceeds 80%, new entries are
    refused with a usage meter — the agent must consolidate first via
    memory_replace (Hermes' bounded-memory rule, no silent truncation).
    """
    path = _memory_path()
    if target.lower() not in ("memory.md", "memory", "facts"):
        target = "MEMORY.md"
    path = path.parent / target if "/" not in target else path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"- [{time.strftime('%Y-%m-%d')}] {content.strip()}"
    if path.exists():
        n, used, budget = _memory_stats(path)
        if used > MEMORY_WARN_AT * budget:
            return ("[error] 记忆库已满（{} 条 · {}% 用量），拒绝新增。"
                    "先 memory_recall 看全量，再用 memory_replace 合并过时/同类条目腾出空间后重试。").format(n, min(999, used * 100 // budget))
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    _notify_memory_changed()
    return f"[ok] 已记住: {content.strip()[:60]}"


def memory_recall() -> str:
    """Read back stored memory (Hermes memory recall). Includes usage meter."""
    path = _memory_path()
    if not path.exists():
        return "(暂无记忆)"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return "(暂无记忆)"
    try:
        meter = memory_usage()
    except Exception:
        meter = ""
    return f"{text}\n\n{meter}".strip()


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
    _notify_memory_changed()
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
    _notify_memory_changed()
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
        f"## 做法\n{instructions.strip()}\n"
    )
    (target / "SKILL.md").write_text(body, encoding="utf-8")
    return f"[ok] 已创建技能 {safe}（SKILL.md 已写入）"


def record_verified_action(
    action_name: str,
    target_app: str,
    steps: list[str] | str,
    verification: str,
    notes: str = ""
) -> str:
    """Decompose and persist a verified action into both skills and MEMORY.md."""
    import re as _re
    safe_name = _re.sub(r"[^a-z0-9_-]", "_", action_name.lower()).strip("_")
    if not safe_name:
        safe_name = "action_" + str(int(time.time()))

    if isinstance(steps, str):
        steps_list = [s.strip() for s in steps.splitlines() if s.strip()]
    else:
        steps_list = list(steps)

    desc = f"{target_app} - {action_name} 操作自动化 SOP（经实机验证生效）"
    steps_md = "\n".join(f"{i}. {s}" for i, s in enumerate(steps_list, 1))

    instructions = (
        f"### 目标应用: {target_app}\n\n"
        f"### 拆解执行步骤 (SOP):\n{steps_md}\n\n"
        f"### 验证方法:\n{verification}\n"
    )
    if notes:
        instructions += f"\n### 关键经验与坐标规律:\n{notes}\n"

    # 1. Persist skill
    skills_dir = _skills_dir()
    target_dir = skills_dir / safe_name
    target_dir.mkdir(parents=True, exist_ok=True)
    body = (
        f"---\nname: {safe_name}\ndescription: {desc}\n---\n\n"
        f"# {safe_name}\n\n"
        f"## 何时使用\n{desc}\n\n"
        f"## 做法\n{instructions.strip()}\n"
    )
    (target_dir / "SKILL.md").write_text(body, encoding="utf-8")

    # 2. Persist to MEMORY.md
    first_step = steps_list[0] if steps_list else ""
    summary = f"[{target_app}] 已验证操作 '{action_name}': {first_step} 等 {len(steps_list)} 步流程，已沉淀至技能 {safe_name}"
    mem_res = memory_add(summary)

    return f"[ok] 操作 '{action_name}' 已拆解沉淀：技能 workspace/skills/{safe_name}/SKILL.md 已写入，长期记忆已同步（{mem_res}）。"


def skill_improve(name: str, note: str = "") -> str:
    """Improve an existing skill by appending a usage note (Hermes self-improve).

    Core skills are NOT modified — improvements go to workspace/skills/_ext/.
    User skills and ext skills are modified directly.
    """
    import re as _re

    skills_dir = _skills_dir()
    safe = _re.sub(r"[^a-z0-9_-]", "_", name.lower()).strip("_")

    # 1. Check user skills (workspace/skills/<name>/)
    user_target = skills_dir / safe / "SKILL.md"
    if user_target.exists():
        _append_usage_note(user_target, note)
        return f"[ok] 已改进技能 {safe}（用户技能）"

    # 2. Check ext skills (workspace/skills/_ext/<name>/)
    ext_target = skills_dir / "_ext" / safe / "SKILL.md"
    if ext_target.exists():
        _append_usage_note(ext_target, note)
        return f"[ok] 已改进技能 {safe}（ext 层）"

    # 3. Check core skills — if found, create ext override
    core_skills_dir = Path(__file__).parent / "_default_skills"
    core_target = core_skills_dir / safe / "SKILL.md"
    if core_target.exists():
        # Create ext override with usage note
        ext_dir = skills_dir / "_ext" / safe
        ext_dir.mkdir(parents=True, exist_ok=True)
        ext_file = ext_dir / "SKILL.md"
        core_text = core_target.read_text(encoding="utf-8")
        ts = time.strftime("%Y-%m-%d")
        note_line = f"- [{ts}] {note.strip()}" if note.strip() else f"- [{ts}] (使用改进)"
        # Add usage note to the ext override
        if "## 使用记录" not in core_text:
            ext_text = core_text + f"\n## 使用记录\n{note_line}\n"
        else:
            ext_text = core_text.replace("## 使用记录", f"## 使用记录\n{note_line}", 1)
        ext_file.write_text(ext_text, encoding="utf-8")
        return f"[ok] 已改进技能 {safe}（core → ext 层，core 未修改）"

    # 4. Fuzzy match
    for d in skills_dir.iterdir():
        if d.is_dir() and safe in d.name.lower():
            _append_usage_note(d / "SKILL.md", note)
            return f"[ok] 已改进技能 {d.name}（模糊匹配）"

    return f"[error] 技能不存在: {name}"


def _append_usage_note(path: Path, note: str) -> None:
    """Append a usage note to a skill file."""
    text = path.read_text(encoding="utf-8")
    ts = time.strftime("%Y-%m-%d")
    note_line = f"- [{ts}] {note.strip()}" if note.strip() else f"- [{ts}] (使用改进)"
    if "## 使用记录" not in text:
        text += f"\n## 使用记录\n{note_line}\n"
    else:
        text = text.replace("## 使用记录", f"## 使用记录\n{note_line}", 1)
    path.write_text(text, encoding="utf-8")


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

MEMORY_REMOVE_DEF = {
    "type": "function",
    "function": {
        "name": "memory_remove",
        "description": "删除一条包含指定内容的记忆条目（先 memory_recall 找到原文再删）。",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要删除的记忆中包含的文字"},
            },
            "required": ["content"],
        },
    },
}

RECORD_VERIFIED_ACTION_DEF = {
    "type": "function",
    "function": {
        "name": "record_verified_action",
        "description": "当一次桌面 GUI 或系统操作真实生效并验证后，立即调用此工具将操作拆解沉淀为可复用技能与记忆（写入 SKILL.md 与 MEMORY.md）。",
        "parameters": {
            "type": "object",
            "properties": {
                "action_name": {"type": "string", "description": "操作名称（如 update_cc_switch_remark）"},
                "target_app": {"type": "string", "description": "目标应用或系统（如 CC Switch、微信、ChatGPT）"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "拆解后的操作步骤列表（含唤醒、坐标、悬浮、输入等关键要素）",
                },
                "verification": {"type": "string", "description": "验证方法（如 SQLite 校验、UI 文本核验）"},
                "notes": {"type": "string", "description": "经验总结、坐标规律或注意事项", "default": ""},
            },
            "required": ["action_name", "target_app", "steps", "verification"],
        },
    },
}


LEARNING_TOOLS: dict[str, dict] = {
    "memory_add": {"def": MEMORY_ADD_DEF, "fn": memory_add},
    "memory_recall": {"def": MEMORY_RECALL_DEF, "fn": memory_recall},
    "memory_replace": {"def": MEMORY_REPLACE_DEF, "fn": memory_replace},
    "memory_remove": {"def": MEMORY_REMOVE_DEF, "fn": memory_remove},
    "skill_create": {"def": SKILL_CREATE_DEF, "fn": skill_create},
    "skill_improve": {"def": SKILL_IMPROVE_DEF, "fn": skill_improve},
    "record_verified_action": {"def": RECORD_VERIFIED_ACTION_DEF, "fn": record_verified_action},
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
（自学习）回顾刚才的对话与操作，判断是否有值得沉淀的东西。如果有，调用相应工具：
- 真实执行了多步 GUI / 系统操作并验证成功 → record_verified_action 拆分沉淀
- 用户透露了持久的偏好/事实 → memory_add
- 发现了一个可复用的解决流程 → skill_create
如果没什么可沉淀的，直接回复 "无需沉淀" 三个字，不要调用工具。
"""


def nudge_prompt() -> str:
    """Return the self-improve nudge prompt (injected every N turns)."""
    return NUDGE_PROMPT