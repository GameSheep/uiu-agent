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
            parts.append(f"# MEMORY (across sessions)\n{self.memory}")
        if not parts:
            parts.append("You are a helpful assistant.")
        return "\n\n".join(parts)


def find_workspace() -> Path:
    """Locate workspace dir: $MYAGENT_WORKSPACE > ./workspace > ~/.my-agent/workspace."""
    env = os.environ.get("MYAGENT_WORKSPACE")
    candidates = [Path(env).expanduser()] if env else []
    candidates += [Path.cwd() / "workspace", Path.home() / ".my-agent" / "workspace"]
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

    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            text = skill_file.read_text(encoding="utf-8")
            name, description, body = _parse_skill_md(text, fallback_name=skill_dir.name)
            ws.skills.append(Skill(name=name, description=description, body=body, path=skill_file))

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