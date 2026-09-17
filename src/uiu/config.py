"""Config layer: workspace/config.yaml (non-secret) + .env (secrets).

Layout:
    workspace/
    ├── config.yaml      # model name, channels list, agent_name (NO secrets)
    ├── .env             # OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, etc.
    ├── SOUL.md
    ├── IDENTITY.md
    ├── USER.md
    ├── MEMORY.md
    └── skills/

Secrets NEVER go in config.yaml. Channels reference secrets by *env var name*
(``secret: OPENAI_API_KEY``) which is resolved at runtime.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------- model ----------

# api_mode values aligned with Hermes: chat_completions | anthropic_messages | bedrock_converse
API_MODES = ("chat_completions", "anthropic_messages", "bedrock_converse")


@dataclass
class ModelConfig:
    """Hermes-style model slot: provider / default / base_url / api_mode."""

    provider: str = "openai"          # provider slug (from providers registry)
    default: str = "gpt-4o-mini"      # the actual model id (Hermes calls this `default`)
    base_url: str = ""                # empty = use provider profile default
    api_mode: str = "chat_completions"
    temperature: float = 0.7
    max_tokens: int = 4096
    api_key_env: str = ""             # resolved from provider profile at load; kept for compat

    @property
    def model(self) -> str:
        """Backward-compat alias: Hermes config.yaml uses `default`, code uses `.model`."""
        return self.default

    @model.setter
    def model(self, value: str) -> None:
        self.default = value

    def resolved_api_key(self) -> str:
        env_name = self.api_key_env
        if not env_name:
            # derive from provider profile if not set
            try:
                from .providers import find_profile
                prof = find_profile(self.provider)
                if prof:
                    env_name = prof.api_key_env
            except Exception:
                pass
        # 1. os.environ (highest priority: already loaded or explicitly set)
        val = os.environ.get(env_name, "") if env_name else ""
        if val:
            return val
        # 2. fallback: read from workspace .env files directly (any cwd)
        if env_name:
            for env_path in (
                Path.cwd() / ".env",
                Path.cwd() / "workspace" / ".env",
                Path.home() / ".uiu" / "workspace" / ".env",
            ):
                try:
                    if env_path.exists():
                        val = parse_env_file(env_path).get(env_name, "")
                        if val:
                            return val
                except Exception:
                    continue
        return ""


# ---------- channel ----------

@dataclass
class ChannelConfig:
    type: str                          # telegram | discord | slack | ...
    name: str                          # unique handle for this channel instance
    enabled: bool = True
    secret_env: str = ""               # env var name holding the token (e.g. TELEGRAM_BOT_TOKEN)
    options: dict[str, Any] = field(default_factory=dict)

    def resolved_token(self) -> str:
        return os.environ.get(self.secret_env, "") if self.secret_env else ""


# ---------- root config ----------

@dataclass
class AppConfig:
    agent_name: str = "uiu"
    model: ModelConfig = field(default_factory=ModelConfig)
    channels: list[ChannelConfig] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    tui: dict[str, Any] = field(default_factory=dict)   # UI 偏好：theme 等
    # 会话生命周期（审计 §3.5）：只提示不擅自删除；要自动裁剪必须显式打开
    sessions_keep: int = 200                  # 超过这个数量就提示（<=0 表示不限制）
    sessions_max_age_days: float = 0.0        # >0 时表示超过这么多天的会话算过期
    sessions_auto_prune: bool = False         # 默认关：daemon 只告警，不替用户删

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "model": asdict(self.model),
            "channels": [asdict(c) for c in self.channels],
            "mcp_servers": self.mcp_servers,
            "tui": self.tui,
            "sessions_keep": self.sessions_keep,
            "sessions_max_age_days": self.sessions_max_age_days,
            "sessions_auto_prune": self.sessions_auto_prune,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        m = dict(d.get("model") or {})
        # legacy migration: old config.yaml used `model:` as a plain string or
        # ModelConfig had `model` field; Hermes format uses `default`
        if isinstance(m, str):
            m = {"default": m}
        elif "model" in m and "default" not in m:
            m["default"] = m.pop("model")
        channels = [ChannelConfig(**c) for c in (d.get("channels") or [])]
        mcp_servers = d.get("mcp_servers", [])
        tui = d.get("tui") or {}
        if not isinstance(tui, dict):
            tui = {}
        return cls(
            agent_name=d.get("agent_name", "uiu"),
            model=ModelConfig(**m),
            channels=channels,
            mcp_servers=mcp_servers,
            tui=tui,
            # 老配置没有这些字段 → 用默认值（新增字段必须向后兼容）
            sessions_keep=int(d.get("sessions_keep", 200) or 0),
            sessions_max_age_days=float(d.get("sessions_max_age_days", 0.0) or 0.0),
            sessions_auto_prune=bool(d.get("sessions_auto_prune", False)),
        )

    def channel(self, name: str) -> ChannelConfig | None:
        for c in self.channels:
            if c.name == name:
                return c
        return None


def resolve_agent_name(cfg: "AppConfig | None", ws=None) -> str:
    """Display name for the agent (shown in TUI header/status).

    Priority: `uiu config --agent-name X` (config.yaml) > IDENTITY.md parsed
    name (`## 名字` / `# IDENTITY — X`) > "agent". Either is user-editable.
    """
    if cfg is not None and getattr(cfg, "agent_name", "") not in ("", "uiu"):
        return str(cfg.agent_name)[:32]
    try:
        if ws is not None and hasattr(ws, "agent_name"):
            name = ws.agent_name() or "agent"
            return name[:32]
    except Exception:
        pass
    return "agent"


# ---------- .env ----------

ENV_LINE_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$")


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Supports quoted values and # comments."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = ENV_LINE_RE.match(line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1]
        out[k] = v
    return out


def write_env_file(path: Path, values: dict[str, str], overwrite: bool = False) -> None:
    """Write .env. If overwrite=False, only writes keys not already set."""
    existing = parse_env_file(path) if path.exists() else {}
    if overwrite:
        existing = {}
    existing.update(values)
    lines = ["# Generated by uiu CLI", ""]
    for k in sorted(existing):
        v = existing[k]
        # quote values with spaces or special chars
        if any(c in v for c in " #\""):
            v = '"' + v.replace('"', '\\"') + '"'
        lines.append(f"{k}={v}")
    lines.append("")
    from ._atomic import atomic_write_text
    atomic_write_text(path, "\n".join(lines))     # .env 里是密钥，不能写半截


# ---------- config.yaml ----------

def config_yaml_path(workspace: Path) -> Path:
    return workspace / "config.yaml"

def load_config(workspace: Path) -> AppConfig:
    path = config_yaml_path(workspace)
    if not path.exists():
        return AppConfig()
    if not _HAS_YAML:
        # very tiny fallback: only handles top-level scalars + channels list of dicts
        return _load_config_fallback(path)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        from .log import get_logger
        get_logger("config").error("config.yaml 解析失败 (%s): %s: %s", path, type(e).__name__, e)
        raise RuntimeError(f"config.yaml 解析失败 ({path}): {type(e).__name__}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"config.yaml 顶层须为 mapping ({path})")
    from .schema import migrate as _migrate
    data, applied = _migrate("config", data)
    if applied:
        from .log import get_logger
        get_logger("config").info("config.yaml 已迁移: %s", ", ".join(applied))
        try:                       # 把版本号落盘，避免每次启动重复迁移
            text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
            from ._atomic import atomic_write_text
            atomic_write_text(path, text)
        except Exception:
            pass
    try:
        return AppConfig.from_dict(data)
    except Exception as e:
        raise RuntimeError(f"config.yaml 结构非法 ({path}): {type(e).__name__}: {e}") from e


def save_config(workspace: Path, cfg: AppConfig) -> None:
    path = config_yaml_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _HAS_YAML:
        from .schema import stamp as _stamp
        text = yaml.safe_dump(_stamp("config", cfg.to_dict()), allow_unicode=True, sort_keys=False)
        # 原子写：配置被写坏会让所有命令都起不来
        from ._atomic import atomic_write_text
        atomic_write_text(path, text)
    else:
        _save_config_fallback(path, cfg)


def _load_config_fallback(path: Path) -> AppConfig:
    """Minimal hand-rolled YAML-ish loader good enough for our config schema."""
    import json
    data: dict = {}
    # If user hasn't installed pyyaml, we'd be brittle. Encourage pyyaml.
    raise RuntimeError(
        "PyYAML not installed. Run: pip install pyyaml"
    )


def _save_config_fallback(path: Path, cfg: AppConfig) -> None:
    raise RuntimeError(
        "PyYAML not installed. Run: pip install pyyaml"
    )


# ---------- helpers ----------

def ensure_workspace(workspace: Path) -> None:
    """Create workspace from bundled template (or minimal fallback) if missing."""
    workspace.mkdir(parents=True, exist_ok=True)
    _copy_default_workspace(workspace)
    for fname in ("SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"):
        p = workspace / fname
        if not p.exists():
            p.write_text(f"# {fname[:-3]}\n\nTODO: 写点东西。\n", encoding="utf-8")
    (workspace / "skills").mkdir(exist_ok=True)
    (workspace / "logs").mkdir(exist_ok=True)
    env_path = workspace / ".env"
    if not env_path.exists():
        env_path.write_text(
            "# Secrets live here. NEVER commit this file.\n"
            "OPENAI_API_KEY=\n"
            "OPENAI_BASE_URL=https://api.openai.com/v1\n"
            "OPENAI_MODEL=gpt-4o-mini\n",
            encoding="utf-8",
        )


def _copy_default_workspace(workspace: Path) -> None:
    """Copy bundled _default_workspace templates into workspace (never overwrites)."""
    import importlib.resources as resources

    try:
        src = resources.files("uiu") / "_default_workspace"
        if not src.is_dir():
            return
    except Exception:
        return
    for entry in src.rglob("*"):
        if entry.is_dir():
            continue
        rel = entry.relative_to(src)
        dest = workspace / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        from ._atomic import atomic_write_text as _awt
        _awt(dest, entry.read_text(encoding="utf-8"))