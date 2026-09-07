"""Workspace loader: reads SOUL/IDENTITY/USER/MEMORY + skills/ at startup.

Inspired by Hermes Agent's 9-layer workspace pattern, simplified to 4 layers:
- SOUL.md      → persona, values, anti-patterns (system prompt core)
- IDENTITY.md  → public card: name, tone, boundaries
- USER.md      → about the user themselves
- MEMORY.md    → long-term notes that survive across sessions
- skills/      → SKILL.md files, each describing one tool the agent can call
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PERSONA_FILES = ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path

    def to_tool_def(self) -> dict:
        """Convert a skill into an OpenAI tool definition.

        A skill can declare a parameter schema via a fenced block in SKILL.md:

            ```tool_schema
            {
              "type": "object",
              "properties": {"query": {"type": "string"}},
              "required": ["query"]
            }
            ```
        """
        schema = self._extract_schema()
        return {
            "type": "function",
            "function": {
                "name": f"skill_{self.name}",
                "description": self.description.strip(),
                "parameters": schema,
            },
        }

    def _extract_schema(self) -> dict:
        m = re.search(r"```tool_schema\s*(\{.*?\})\s*```", self.body, re.DOTALL)
        if m:
            import json
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return {
            "type": "object",
            "properties": {"input": {"type": "string"}},
            "required": ["input"],
        }


@dataclass
class Workspace:
    root: Path
    soul: str = ""
    identity: str = ""
    user: str = ""
    memory: str = ""
    skills: list[Skill] = field(default_factory=list)

    def system_prompt(self) -> str:
        """Assemble the layered system prompt (Hermes-style, 4 layers)."""
        parts = []
        if self.soul:
            parts.append(f"# SOUL\n{self.soul}")
        if self.identity:
            parts.append(f"# IDENTITY\n{self.identity}")
        if self.user:
            parts.append(f"# USER\n{self.user}")
        if self.memory:
            try:
                from .learning import memory_usage as _usage
                meter = _usage()
            except Exception:
                meter = ""
            parts.append(f"# MEMORY (across sessions) {meter}\n{self.memory}")
        idx = self.skills_index()
        if idx:
            parts.append(
                "# SKILLS（渐进披露：只给了索引，需要时用 skills_list / skill_view 按需取全文，"
                "可执行的 skill_* 工具已在工具列表中）\n" + idx)
        if not parts:
            parts.append("You are a helpful assistant.")
        return "\n\n".join(parts)

    def skills_index(self) -> str:
        """One-line-per-skill index (cheap) — full bodies via skill_view."""
        return "\n".join(f"- {s.name}: {s.description[:160]}" for s in self.skills)

    def agent_name(self) -> str:
        """Display name, editable by the user via IDENTITY.md.

        Recognition order: `## 名字` section > `# IDENTITY — X` heading >
        `名字：X` line. Fallback: "agent".
        """
        text = self.identity or ""
        m = re.search(r"^##?\s*名字\s*\n+\s*(\S+)", text, re.M)
        if m:
            return m.group(1).strip()[:32]
        m = re.search(r"^#\s*IDENTITY\s*[—\-–:：]\s*(\S+)", text, re.M)
        if m:
            return m.group(1).strip()[:32]
        m = re.search(r"名字\s*[：:]\s*(\S+)", text)
        if m:
            return m.group(1).strip()[:32]
        return "agent"

    def reload_memory(self) -> None:
        """Re-read MEMORY.md from disk so running-session context stays fresh.

        Called after memory_add / add_memory / /memory writes so the next
        system prompt includes the new entry without a restart.
        """
        path = self.root / "MEMORY.md"
        if not path.exists():
            self.memory = ""
            return
        try:
            self.memory = path.read_text(encoding="utf-8")
        except OSError:
            pass


def find_workspace() -> Path:
    """Locate workspace dir: $UIU_WORKSPACE > ./workspace > ~/.uiu/workspace."""
    env = os.environ.get("UIU_WORKSPACE")
    candidates = [Path(env).expanduser()] if env else []
    candidates += [Path.cwd() / "workspace", Path.home() / ".uiu" / "workspace"]
    for p in candidates:
        if (p / "SOUL.md").exists() or (p / "IDENTITY.md").exists() or p.is_dir():
            return p
    return candidates[-1]


def load_workspace(root: Path | None = None) -> Workspace:
    root = Path(root) if root else find_workspace()
    root.mkdir(parents=True, exist_ok=True)

    ws = Workspace(root=root)
    for name in PERSONA_FILES:
        path = root / name
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            print(f"[workspace] skip {name}: {e}", file=sys.stderr)
            continue
        setattr(ws, name.replace(".md", "").lower(), content)

    # Load skills: core (package + workspace/_default) + ext (workspace/_ext overrides)
    # Ext skills with same name override core skills
    skills_map: dict[str, Skill] = {}

    # 1. Core skills from package directory
    for core_dir in (
        Path(__file__).parent / "_default_skills",
        root / "skills" / "_default",   # synced via `uiu update skills`
    ):
        if not core_dir.is_dir():
            continue
        for skill_dir in sorted(core_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError as e:
                print(f"[workspace] skip skill {skill_dir.name}: {e}", file=sys.stderr)
                continue
            name, description, body = _parse_skill_md(text, fallback_name=skill_dir.name)
            # package core wins over synced _default copy (keep original if exists)
            skills_map.setdefault(name, Skill(name=name, description=description, body=body, path=skill_file))

    # 2. Ext skills from workspace (override core)
    ext_skills_dir = root / "skills" / "_ext"
    if ext_skills_dir.is_dir():
        for skill_dir in sorted(ext_skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError as e:
                print(f"[workspace] skip skill {skill_dir.name}: {e}", file=sys.stderr)
                continue
            name, description, body = _parse_skill_md(text, fallback_name=skill_dir.name)
            skills_map[name] = Skill(name=name, description=description, body=body, path=skill_file)

    # 3. User skills from workspace/skills (non-_ dirs, override core)
    user_skills_dir = root / "skills"
    if user_skills_dir.is_dir():
        for skill_dir in sorted(user_skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError as e:
                print(f"[workspace] skip skill {skill_dir.name}: {e}", file=sys.stderr)
                continue
            name, description, body = _parse_skill_md(text, fallback_name=skill_dir.name)
            skills_map[name] = Skill(name=name, description=description, body=body, path=skill_file)

    ws.skills = list(skills_map.values())
    return ws


def _parse_skill_md(text: str, fallback_name: str) -> tuple[str, str, str]:
    """Parse SKILL.md: front-matter style with --- separators.

    Expected layout:
        ---
        name: my_skill
        description: One line describing when to use this skill.
        ---

        Optional body with instructions for the agent and a ```tool_schema``` block.
    """
    name = fallback_name
    description = ""
    body = text
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        if m:
            fm, body = m.group(1), m.group(2)
            for line in fm.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    if k.strip() == "name":
                        name = v.strip()
                    elif k.strip() == "description":
                        description = v.strip()
    if not description:
        description = body.strip().splitlines()[0] if body.strip() else name
    return name, description, body