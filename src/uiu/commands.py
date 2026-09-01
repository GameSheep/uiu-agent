"""CLI subcommands: init, show, model, config, skills, channel, update, version.

Each subcommand is a function ``cmd_<name>(args, workspace) -> int``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import tools
from .config import (
    AppConfig,
    ChannelConfig,
    ModelConfig,
    config_yaml_path,
    ensure_workspace,
    load_config,
    parse_env_file,
    save_config,
    write_env_file,
)
from .workspace import load_workspace


# ---------- helpers ----------

def _workspace(args) -> Path:
    ws_arg = getattr(args, "workspace", None) or os.environ.get("UIU_WORKSPACE")
    if ws_arg:
        return Path(ws_arg).expanduser()
    return Path.cwd() / "workspace"


def _print_ok(msg: str) -> None:
    print(f"[ok] {msg}")


def _print_err(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr)


def _confirm(prompt: str, default_yes: bool = False) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes")


# ---------- init ----------

def cmd_init(args) -> int:
    ws = _workspace(args)
    ensure_workspace(ws)
    cfg = load_config(ws)
    if not config_yaml_path(ws).exists():
        save_config(ws, cfg)
        _print_ok(f"created {ws}")
    else:
        _print_ok(f"workspace already exists: {ws}")

    if not parse_env_file(ws / ".env").get("OPENAI_API_KEY"):
        print()
        print("next: edit your API key in one of two ways")
        print(f"  1) edit {ws / '.env'} directly")
        print(f"  2) uiu config --api-key sk-xxx")
    return 0


# ---------- show ----------

def cmd_show(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    print(f"workspace:  {ws}")
    print(f"config:     {config_yaml_path(ws)}")
    print(f"agent_name: {cfg.agent_name}")
    print()
    print("model:")
    print(f"  provider:    {cfg.model.provider}")
    print(f"  base_url:    {cfg.model.base_url}")
    print(f"  model:       {cfg.model.model}")
    print(f"  api_key_env: {cfg.model.api_key_env}  -> {'set' if cfg.model.resolved_api_key() else 'NOT SET'}")
    print(f"  temperature: {cfg.model.temperature}")
    print(f"  max_tokens:  {cfg.model.max_tokens}")
    print()
    print(f"channels ({len(cfg.channels)}):")
    if not cfg.channels:
        print("  (none — try: uiu channel add telegram)")
    for c in cfg.channels:
        status = "enabled" if c.enabled else "disabled"
        token = c.resolved_token()
        token_state = "token set" if token else "TOKEN NOT SET"
        print(f"  - {c.name} [{c.type}] {status}, {token_state}, secret={c.secret_env}")
    return 0


# ---------- model ----------

def cmd_model(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    m = cfg.model

    changed = False
    if args.set_provider:
        m.provider = args.set_provider
        changed = True
    if args.set_base_url:
        m.base_url = args.set_base_url
        changed = True
    if args.set_model:
        m.model = args.set_model
        changed = True
    if args.set_api_key_env:
        m.api_key_env = args.set_api_key_env
        changed = True
    if args.set_temperature is not None:
        m.temperature = args.set_temperature
        changed = True
    if args.set_max_tokens is not None:
        m.max_tokens = args.set_max_tokens
        changed = True

    if not changed:
        print(f"provider:    {m.provider}")
        print(f"base_url:    {m.base_url}")
        print(f"model:       {m.model}")
        print(f"api_key_env: {m.api_key_env}")
        print(f"temperature: {m.temperature}")
        print(f"max_tokens:  {m.max_tokens}")
        return 0

    save_config(ws, cfg)
    _print_ok(f"model updated -> {m.provider}/{m.model}")
    return 0


# ---------- config (secrets + workspace) ----------

def cmd_config(args) -> int:
    ws = _workspace(args)

    if args.api_key:
        # route to .env using model's api_key_env key
        cfg = load_config(ws)
        key = cfg.model.api_key_env
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[key] = args.api_key
        write_env_file(env_path, existing)
        _print_ok(f"wrote {key} to {env_path}")
        return 0

    if args.set_secret:
        key, _, value = args.set_secret.partition("=")
        if not value:
            _print_err("format: KEY=VALUE")
            return 2
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[key.strip()] = value
        write_env_file(env_path, existing)
        _print_ok(f"set {key.strip()} in {env_path}")
        return 0

    if args.unset_secret:
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        if args.unset_secret in existing:
            del existing[args.unset_secret]
            write_env_file(env_path, existing)
            _print_ok(f"unset {args.unset_secret}")
        return 0

    if args.list:
        env_path = ws / ".env"
        for k, v in sorted(parse_env_file(env_path).items()):
            shown = v if args.show_values else (v[:4] + "…" + v[-2:] if len(v) > 10 else "(set)")
            print(f"  {k} = {shown}")
        return 0

    print("usage: uiu config [--api-key KEY | --set-secret K=V | --unset-secret K | --list]")
    return 2


# ---------- skills ----------

def cmd_skills(args) -> int:
    ws = _workspace(args)
    skills_dir = ws / "skills"

    if args.action == "list":
        if not skills_dir.is_dir():
            print("(no skills directory)")
            return 0
        any_shown = False
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            sk = d / "SKILL.md"
            if not sk.exists():
                continue
            text = sk.read_text(encoding="utf-8", errors="replace").splitlines()
            name = d.name
            desc = ""
            for line in text:
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    break
            print(f"  {name:<24} {desc[:70]}")
            any_shown = True
        if not any_shown:
            print("(no skills — try: uiu skills add echo)")
        return 0

    if args.action == "add":
        name = args.name
        target = skills_dir / name
        if target.exists():
            _print_err(f"skill already exists: {target}")
            return 2
        template = (
            f"---\nname: {name}\ndescription: TODO: describe when to use this skill.\n---\n\n"
            "exec: \n\n"
            "```tool_schema\n"
            "{\n"
            '  "type": "object",\n'
            '  "properties": {"input": {"type": "string"}},\n'
            '  "required": ["input"]\n'
            "}\n"
            "```\n"
        )
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(template, encoding="utf-8")
        _print_ok(f"created {target / 'SKILL.md'}")
        print("edit it, then it'll be picked up on next `uiu` start")
        return 0

    if args.action == "edit":
        target = skills_dir / args.name / "SKILL.md"
        if not target.exists():
            _print_err(f"no such skill: {args.name}")
            return 2
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
        try:
            subprocess.run([editor, str(target)], check=False)
        except FileNotFoundError:
            _print_err(f"editor '{editor}' not found; set $EDITOR")
            return 2
        return 0

    if args.action == "path":
        print(skills_dir)
        return 0

    return 2


# ---------- channel ----------

def cmd_channel(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)

    if args.action == "list":
        if not cfg.channels:
            print("(no channels)")
            return 0
        for c in cfg.channels:
            tok = "ok" if c.resolved_token() else "MISSING"
            flag = "on" if c.enabled else "off"
            print(f"  {c.name:<20} {c.type:<10} [{flag}] token:{tok} secret={c.secret_env}")
        return 0

    if args.action == "add":
        name = args.name
        if cfg.channel(name):
            _print_err(f"channel name already exists: {name}")
            return 2
        ctype = args.type
        secret_env = args.secret_env or _default_secret_env(ctype)
        options = _parse_options(args.option)
        cfg.channels.append(ChannelConfig(
            type=ctype,
            name=name,
            secret_env=secret_env,
            options=options,
        ))
        save_config(ws, cfg)
        _print_ok(f"added channel '{name}' [{ctype}]")
        if not os.environ.get(secret_env) and not parse_env_file(ws / ".env").get(secret_env):
            print(f"  next: uiu config --set-secret {secret_env}=<token>")
            print(f"        (or set it via your platform)")
        return 0

    if args.action == "enable" or args.action == "disable":
        c = cfg.channel(args.name)
        if not c:
            _print_err(f"unknown channel: {args.name}")
            return 2
        c.enabled = (args.action == "enable")
        save_config(ws, cfg)
        _print_ok(f"{args.action}d {args.name}")
        return 0

    if args.action == "remove":
        cfg.channels = [c for c in cfg.channels if c.name != args.name]
        save_config(ws, cfg)
        _print_ok(f"removed {args.name}")
        return 0

    if args.action == "test":
        c = cfg.channel(args.name)
        if not c:
            _print_err(f"unknown channel: {args.name}")
            return 2
        token = c.resolved_token()
        if not token:
            _print_err(f"{c.secret_env} not set in .env or env. run: uiu config --set-secret {c.secret_env}=...")
            return 2
        # dispatch to adapter
        try:
            from . import channels
            ok, msg = channels.test(c)
        except Exception as e:
            _print_err(f"test failed: {type(e).__name__}: {e}")
            return 1
        print(msg)
        return 0 if ok else 1

    return 2


def _default_secret_env(ctype: str) -> str:
    return {
        "telegram": "TELEGRAM_BOT_TOKEN",
        "discord": "DISCORD_BOT_TOKEN",
        "slack": "SLACK_BOT_TOKEN",
        "whatsapp": "WHATSAPP_TOKEN",
    }.get(ctype, f"{ctype.upper()}_TOKEN")


def _parse_options(items: list[str] | None) -> dict:
    if not items:
        return {}
    out: dict[str, str] = {}
    for it in items:
        if "=" not in it:
            continue
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# ---------- update ----------

def cmd_update(args) -> int:
    ws = _workspace(args)
    if args.what == "self":
        if getattr(args, "no_pull", False):
            return _update_self_no_pull()
        return _update_self()
    if args.what == "skills":
        return _update_default_skills(ws)
    return 2


def _update_self_no_pull() -> int:
    print("· pip: reinstalling (editable, no git pull)…")
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
        check=False,
    )
    if rc.returncode != 0:
        _print_err("pip install failed")
        return 1
    _print_ok("reinstalled — restart agent to pick up changes")
    return 0


def _update_self() -> int:
    """Stable, idempotent update. Three layers:

    1. git pull        — fetch latest code (if repo has a remote)
    2. pip install -e  — reinstall so new deps/code are active
    3. report status   — tell user what changed

    Never touches workspace/ (SOUL/IDENTITY/USER are the user's own IP).
    If git pull conflicts (local edits), it stops and tells the user,
    rather than silently overwriting.
    """
    ok = True

    # Layer 1: git
    if _in_git_repo():
        remotes = _git_remotes()
        if remotes:
            print("· git: pulling latest code…")
            rc = _git(["pull", "--ff-only"])
            if rc != 0:
                _print_err("git pull failed (maybe local edits conflict with upstream?)")
                print("  → fix conflicts, or skip remote updates with: uiu update self --no-pull")
                ok = False
        else:
            print("· git: no remote configured — skipping pull (local repo only)")
    else:
        print("· git: not a git repository — skipping (run `git init` to enable)")

    # Layer 2: pip reinstall
    print("· pip: reinstalling (editable)…")
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
        check=False,
    )
    if rc.returncode != 0:
        _print_err("pip install failed")
        ok = False

    if ok:
        _print_ok("update complete — restart your agent to pick up changes")
        return 0
    return 1


# ---------- git helpers ----------

def _in_git_repo() -> bool:
    rc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    return rc.returncode == 0


def _git_remotes() -> list[str]:
    rc = subprocess.run(
        ["git", "remote"],
        capture_output=True, text=True,
    )
    if rc.returncode != 0:
        return []
    return [l.strip() for l in rc.stdout.splitlines() if l.strip()]


def _git(args: list[str]) -> int:
    rc = subprocess.run(["git", *args], check=False)
    return rc.returncode


def _update_default_skills(ws: Path) -> int:
    """Sync default skills shipped with the package into workspace/skills/_default/."""
    import importlib.resources as resources
    try:
        pkg_root = resources.files("uiu")
    except Exception:
        pkg_root = None

    if pkg_root is None or not (pkg_root / "_default_skills").is_dir():
        print("(no default skills bundled)")
        return 0

    target = ws / "skills" / "_default"
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for entry in (pkg_root / "_default_skills").iterdir():  # type: ignore[attr-defined]
        if not entry.is_dir():
            continue
        dest = target / entry.name
        if dest.exists():
            continue
        shutil.copytree(str(entry), str(dest))
        copied += 1
    _print_ok(f"synced {copied} default skill(s) into {target}")
    return 0


# ---------- version ----------

def cmd_version(args) -> int:
    from . import __version__
    print(f"uiu {__version__}")
    return 0