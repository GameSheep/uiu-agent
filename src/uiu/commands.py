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
    from .providers import get_profile, load_builtin_profiles
    load_builtin_profiles()
    ws = _workspace(args)
    cfg = load_config(ws)
    m = cfg.model
    prof = get_profile(m.provider)
    base_url = m.base_url or (prof.base_url if prof else "(未设)")
    key_env = m.api_key_env or (prof.api_key_env if prof else "")
    print(f"workspace:  {ws}")
    print(f"config:     {config_yaml_path(ws)}")
    print(f"agent_name: {cfg.agent_name}")
    print()
    print("model:")
    print(f"  provider:    {m.provider}")
    print(f"  base_url:    {base_url}")
    print(f"  model:       {m.model}")
    print(f"  api_mode:    {m.api_mode}")
    print(f"  api_key_env: {key_env}  -> {'set' if m.resolved_api_key() else 'NOT SET'}")
    print(f"  temperature: {m.temperature}")
    print(f"  max_tokens:  {m.max_tokens}")
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

    # --refresh: wipe model picker cache (Hermes behavior)
    if getattr(args, "refresh", False):
        try:
            from .providers import _MODELS_CACHE
            _MODELS_CACHE.clear()
            print("  Cleared model picker cache.")
        except Exception:
            pass

    # non-interactive: any --set-* flag present
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
    if args.set_api_key:
        # write key into .env under the model's api_key_env
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[m.api_key_env] = args.set_api_key
        write_env_file(env_path, existing)
        _print_ok(f"wrote key to {env_path}")
        return 0

    if changed:
        save_config(ws, cfg)
        _print_ok(f"model updated -> {m.provider}/{m.model}")
        return 0

    # --- interactive wizard ---
    return _model_wizard(ws, cfg)


def _model_wizard(ws: Path, cfg: AppConfig) -> int:
    from .providers import get_profile, list_profiles, load_builtin_profiles

    load_builtin_profiles()
    m = cfg.model
    cur_profile = get_profile(m.provider)
    print(f"当前模型: [{m.provider}] {m.model}")
    print(f"  base_url: {m.base_url or (cur_profile.base_url if cur_profile else '(未设)')}")
    print(f"  api_mode: {m.api_mode}")
    print()

    profiles = list_profiles()

    # step 1: choose provider
    print("选择 provider:")
    for i, p in enumerate(profiles, 1):
        marker = " *" if p.name.lower() == m.provider.lower() else ""
        print(f"  {i}. {p.display_name}  ({p.description}){marker}")
    print(f"  {len(profiles)+1}. 保持当前配置")
    try:
        choice = input(f"> 输入数字 [1-{len(profiles)+1}]: ").strip()
    except EOFError:
        return 0
    if choice == str(len(profiles) + 1):
        return 0
    try:
        idx = int(choice) - 1
        profile = profiles[idx]
    except (ValueError, IndexError):
        _print_err("无效选择")
        return 2

    if profile.name == "custom":
        m.provider = "custom"
        m.base_url = input("base_url (如 https://api.xxx.com/v1): ").strip() or m.base_url
        m.api_key_env = input(f"API key 环境变量名 (默认 {m.api_key_env or 'CUSTOM_API_KEY'}): ").strip() or m.api_key_env or "CUSTOM_API_KEY"
        m.model = input("model 名 (如 gpt-4o-mini): ").strip() or m.model
        api_mode_choice = input(f"api_mode (chat_completions/anthropic_messages, 默认 {m.api_mode}): ").strip()
        if api_mode_choice:
            m.api_mode = api_mode_choice
    else:
        m.provider = profile.name
        m.base_url = ""  # empty = use profile default (Hermes clears base_url on switch)
        m.api_key_env = profile.api_key_env
        m.api_mode = profile.api_mode

        # step 1b: fetch live model list (Hermes picker behavior), fallback to curated
        key = m.resolved_api_key()
        models = profile.available_models(key)
        if not models:
            _print_err(f"无法获取 {profile.display_name} 模型列表（无网络/key？）")
            return 2
        m.model = models[0] if profile.fallback_models else m.model
        print(f"\n{profile.display_name} 可用模型 ({'live' if key and models != list(profile.fallback_models) else 'fallback'}):")
        for i, model in enumerate(models, 1):
            marker = " *" if model == m.model else ""
            print(f"  {i}. {model}{marker}")
        print(f"  {len(models)+1}. 自定义")
        model_choice = input(f"> 输入数字 [1-{len(models)+1}] (默认 {m.model}): ").strip()
        if model_choice:
            try:
                mi = int(model_choice) - 1
                if 0 <= mi < len(models):
                    m.model = models[mi]
                elif model_choice == str(len(models) + 1):
                    m.model = input("model 名: ").strip()
            except ValueError:
                m.model = model_choice

    save_config(ws, cfg)
    _print_ok(f"已保存: {m.provider} / {m.model}")

    # step 2: API key (skip for auth_type=none providers like ollama)
    profile = get_profile(m.provider)
    need_key = profile is None or profile.auth_type != "none"
    if need_key:
        current = m.resolved_api_key()
        env_name = m.api_key_env or "API_KEY"
        if not current:
            key_input = input(f"\n输入 {env_name} (留空跳过): ").strip()
            if key_input:
                env_path = ws / ".env"
                existing = parse_env_file(env_path)
                existing[env_name] = key_input
                write_env_file(env_path, existing)
                _print_ok(f"已写入 {env_name}")
        else:
            print(f"\n{env_name} 已设置（{current[:6]}…），如需更换输入新 key:")
            key_input = input(f"新 {env_name} (留空保留): ").strip()
            if key_input:
                env_path = ws / ".env"
                existing = parse_env_file(env_path)
                existing[env_name] = key_input
                write_env_file(env_path, existing)
                _print_ok(f"已更新 {env_name}")

    # step 3: test connection
    test_choice = input("\n测试连接？[Y/n]: ").strip().lower()
    if test_choice in ("", "y", "yes"):
        return _test_model_connection(ws, cfg)
    return 0


def _test_model_connection(ws: Path, cfg: AppConfig) -> int:
    """Quick connectivity test: send a trivial chat completion."""
    from .providers import get_profile
    m = cfg.model
    key = m.resolved_api_key()
    profile = get_profile(m.provider)
    base_url = m.base_url or (profile.base_url if profile else "")
    if not base_url:
        _print_err("base_url 未设置，跳过测试")
        return 0
    if not key and not (profile and profile.auth_type == "none"):
        _print_err(f"{m.api_key_env} 未设置，跳过测试")
        return 0
    print(f"· 测试 {m.provider} / {m.model} @ {base_url} …")
    try:
        from .llm import make_client
        client = make_client(m)
        resp = client.chat.completions.create(
            model=m.model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        reply = resp.choices[0].message.content or ""
        _print_ok(f"连接成功！模型回复: {reply[:60]}")
        return 0
    except Exception as e:
        _print_err(f"连接失败: {type(e).__name__}: {e}")
        print("  检查 base_url / key / 网络，然后重新运行: uiu model")
        return 1


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
    skills_dir.mkdir(parents=True, exist_ok=True)

    if args.action == "install":
        from .skill_installer import install_skill
        print(install_skill(args.identifier, skills_dir, name_override=args.name, force=args.force))
        return 0

    if args.action == "search":
        from .skill_installer import search_skills
        print(search_skills(args.query, limit=args.limit))
        return 0

    if args.action == "inspect":
        from .skill_installer import parse_identifier, find_skill_files, _http_get
        parsed = parse_identifier(args.identifier)
        if parsed["kind"] == "unknown":
            _print_err(f"无法识别: {args.identifier}")
            return 2
        files = find_skill_files(parsed)
        if not files or files[0].startswith("error:"):
            _print_err(files[0] if files else "未找到 SKILL.md")
            return 2
        for f in files[:3]:
            try:
                if f.startswith("http"):
                    content = _http_get(f).decode("utf-8")
                else:
                    owner, repo, branch = parsed["owner"], parsed["repo"], parsed["branch"]
                    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{f}"
                    content = _http_get(url).decode("utf-8")
                print(f"=== {f} ===")
                print(content[:800])
                print("…" if len(content) > 800 else "")
            except Exception as e:
                _print_err(f"获取失败: {e}")
        print("\n安装: uiu skills install", args.identifier)
        return 0

    if args.action == "reload":
        # clear in-memory skill cache so next load picks up disk changes
        try:
            import uiu.workspace as ws_mod
            # no cache to clear — skills are loaded fresh on each load_workspace call
            pass
        except Exception:
            pass
        print("[ok] skills 已重新加载（下次对话生效）")
        return 0

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
        if ctype == "telegram":
            if not os.environ.get(secret_env) and not parse_env_file(ws / ".env").get(secret_env):
                print(f"  next: uiu config --set-secret {secret_env}=<token>")
        elif ctype == "feishu":
            print("  飞书配置: uiu channel add 需带 -o app_id=... -o app_secret=...")
        elif ctype == "wecom":
            print("  企微配置: uiu channel add 需带 -o corpid=... -o corpsecret=... -o agentid=...")
        elif ctype == "dingtalk":
            print("  钉钉配置: uiu channel add 需带 -o client_id=... -o client_secret=...")
            print("          钉钉开放平台创建机器人，开 Stream 模式")
        elif ctype == "discord":
            if not os.environ.get(secret_env) and not parse_env_file(ws / ".env").get(secret_env):
                print(f"  next: uiu config --set-secret {secret_env}=<token>")
        elif ctype == "slack":
            print("  Slack: uiu config --set-secret SLACK_BOT_TOKEN=xoxb-...")
            print("         并 uiu channel add 带 -o app_token=xapp-...")
        print("  启用: uiu channel enable", name)
        print("  启动网关: uiu serve")
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
        "feishu": "FEISHU_APP_SECRET",
        "wecom": "WECOM_CORP_SECRET",
        "dingtalk": "DINGTALK_CLIENT_SECRET",
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


# ---------- serve (gateway) ----------

def cmd_serve(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    from .gateway import Gateway
    from .workspace import load_workspace
    ws_obj = load_workspace(ws)
    gw = Gateway(cfg, ws_obj)
    gw.run(port=args.port)
    return 0


# ---------- version ----------

def cmd_version(args) -> int:
    from . import __version__
    print(f"uiu {__version__}")
    return 0


# ---------- plugins (provider plugins) ----------

def _plugins_dir() -> Path:
    return Path.home() / ".uiu" / "plugins" / "model-providers"


def cmd_plugins(args) -> int:
    if args.action == "path":
        print(_plugins_dir())
        return 0

    if args.action == "list":
        d = _plugins_dir()
        if not d.is_dir():
            print(f"(no plugins dir — run: uiu plugins new <name>)")
            return 0
        found = False
        for child in sorted(d.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                print(f"  {child.name}/")
                found = True
        if not found:
            print(f"(no plugins in {d})")
        return 0

    if args.action == "new":
        name = args.name
        d = _plugins_dir() / name
        if d.exists():
            _print_err(f"plugin already exists: {d}")
            return 2
        d.mkdir(parents=True, exist_ok=True)
        safe = name.replace("-", "_")
        (d / "__init__.py").write_text(
            f'''"""{name} provider plugin — uiu (Hermes-style).

Self-registers a ProviderProfile on import. Drop this dir into
~/.uiu/plugins/model-providers/ and it shows up in `uiu model`
automatically. Restart uiu (or clear the registry) after editing.
"""
from uiu.providers import ProviderProfile, register_provider

# --- edit below ---
profile = ProviderProfile(
    name="{safe}",
    aliases=(),
    display_name="{name}",
    description="One-line description shown in the picker",
    base_url="https://api.example.com/v1",
    api_key_env="{safe.upper()}_API_KEY",
    fallback_models=("model-a", "model-b"),
    api_mode="chat_completions",   # or anthropic_messages
    auth_type="api_key",           # api_key | none
)

register_provider(profile)
''',
            encoding="utf-8",
        )
        (d / "plugin.yaml").write_text(
            f"""name: {name}-provider
kind: model-provider
version: 1.0.0
description: {name} provider
author: you
""",
            encoding="utf-8",
        )
        _print_ok(f"created plugin: {d}")
        print("  edit __init__.py, then run `uiu model` to see it")
        return 0

    return 2


# ---------- publish ----------

def cmd_publish(args) -> int:
    """Build wheel + sdist and upload to PyPI (or TestPyPI with --test)."""
    token = args.token or os.environ.get("PYPI_TOKEN") or os.environ.get("TWINE_PASSWORD")
    if not token:
        _print_err("no PyPI token. Set PYPI_TOKEN env var or pass --token <token>.")
        print("  create one at https://pypi.org/manage/account/token/")
        return 2

    # 1. build
    print("· building sdist + wheel…")
    rc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "build", "twine"],
        check=False,
    )
    if rc.returncode != 0:
        _print_err("pip install build/twine failed")
        return 1
    rc = subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel"], check=False)
    if rc.returncode != 0:
        _print_err("build failed — fix errors above, then retry")
        return 1

    # 2. upload
    if args.test:
        repo = "https://test.pypi.org/legacy/"
        print(f"· uploading to TestPyPI…")
    else:
        repo = "https://upload.pypi.org/legacy/"
        print(f"· uploading to PyPI…")

    # expand dist/* glob explicitly (Windows subprocess doesn't glob)
    dist_dir = Path("dist")
    artifacts = sorted(dist_dir.glob("*.whl")) + sorted(dist_dir.glob("*.tar.gz"))
    if not artifacts:
        _print_err("no artifacts found in dist/")
        return 1
    rc = subprocess.run(
        [sys.executable, "-m", "twine", "upload", "--repository-url", repo, *map(str, artifacts), "--non-interactive"],
        env={**os.environ, "TWINE_USERNAME": "__token__", "TWINE_PASSWORD": token},
        check=False,
    )
    if rc.returncode != 0:
        _print_err("upload failed — fix errors above, then retry")
        return 1

    if args.test:
        print("  done! try: pip install --index-url https://test.pypi.org/simple/ uiu")
    else:
        print("  done! try: pip install uiu   or   pipx run uiu")
    return 0