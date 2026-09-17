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
    # Default resolution: existing workspace > home (~/.uiu/workspace)
    # Home-priority fallback: no local workspace -> use the personal dir
    for cand in (Path.cwd() / "workspace", Path.home() / "workspace", Path.home() / ".uiu" / "workspace"):
        if (cand / "config.yaml").exists() or (cand / "SOUL.md").exists() or cand.is_dir():
            return cand
    return Path.home() / ".uiu" / "workspace"


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
        _print_ok(f"已创建 {ws}")
    else:
        _print_ok(f"workspace 已存在: {ws}")

    # Browser Use 的 Playwright 浏览器改为后台静默安装（不阻塞 init），失败不影响使用
    _setup_playwright_browsers_async()

    if not parse_env_file(ws / ".env").get("OPENAI_API_KEY"):
        print()
        print("next: edit your API key in one of two ways")
        print(f"  1) edit {ws / '.env'} directly")
        print(f"  2) uiu config --api-key sk-xxx")
    return 0


def _setup_playwright_browsers_async() -> None:
    """Kick off Playwright Chromium install in the background (non-blocking)."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return
    import threading
    print("· 后台安装 Playwright Chromium（不阻塞，可继续使用）…")
    threading.Thread(target=_setup_playwright_browsers, daemon=True).start()


def _setup_playwright_browsers() -> None:
    """Install Playwright browsers for Browser Use (if playwright is available)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            _print_ok("Playwright Chromium 已就绪（Browser Use 可用）")
    except subprocess.TimeoutExpired:
        print("  Playwright 浏览器安装超时（可稍后运行: playwright install chromium）")
    except FileNotFoundError:
        pass



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
    try:
        from .config import resolve_agent_name as _resolve_name
        from .workspace import load_workspace as _load_ws
        print(f"agent:      {_resolve_name(cfg, _load_ws(ws))}  (config --agent-name 或 IDENTITY.md ## 名字)")
    except Exception:
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
    print("tui:")
    try:
        from .app.theme import DEFAULT_THEME, THEMES
        tui = getattr(cfg, "tui", {}) or {}
        theme = str(tui.get("theme") or DEFAULT_THEME)
        theme_note = "" if theme in THEMES else "  (未知主题，会回退默认)"
        print(f"  theme:       {theme}{theme_note}")
        colors = tui.get("colors") or {}
        if colors:
            for slot, value in colors.items():
                print(f"  color.{slot}: {value}")
        else:
            print("  colors:      (无覆盖 — uiu config --color primary=#RRGGBB)")
    except Exception:
        pass
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
        key = _resolve_key_env(ws, cfg)
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[key] = args.set_api_key
        write_env_file(env_path, existing)
        os.environ[key] = args.set_api_key
        _print_ok(f"已写入密钥到 {env_path}")
        return 0

    if changed:
        save_config(ws, cfg)
        _print_ok(f"模型已更新 → {m.provider}/{m.model}")
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
                os.environ[env_name] = key_input  # 立即加载到当前进程
                _print_ok(f"已写入 {env_name}")
        else:
            print(f"\n{env_name} 已设置（{current[:6]}…），如需更换输入新 key:")
            key_input = input(f"新 {env_name} (留空保留): ").strip()
            if key_input:
                env_path = ws / ".env"
                existing = parse_env_file(env_path)
                existing[env_name] = key_input
                write_env_file(env_path, existing)
                os.environ[env_name] = key_input  # 立即加载到当前进程
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
        _print_err(f"{m.api_key_env or 'API key'} 未设置，跳过测试")
        print(f"  → 运行: uiu config --api-key sk-xxx   （或 uiu model 重新选择）")
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
        # friendly classification of common failures
        err_type = type(e).__name__
        hint = ""
        msg = str(e)
        if "401" in msg or "AuthenticationError" in err_type or "invalid_api_key" in msg.lower():
            hint = "\n  → API key 无效或被拒绝。运行: uiu config --api-key 新key\n    或换 provider: uiu model"
        elif "404" in msg or "ModelNotFoundError" in err_type:
            hint = f"\n  → 模型 '{m.model}' 不存在或无权访问。运行: uiu model --set-model 其他模型"
        elif "timeout" in msg.lower() or "timed out" in msg.lower():
            hint = "\n  → 连接超时。检查 base_url 和网络:\n    uiu model --set-base-url https://xxx/v1"
        elif "Connection" in err_type or "APIConnectionError" in err_type:
            hint = "\n  → 无法连接服务器。检查网络或 base_url:\n    uiu model --set-base-url https://xxx/v1"
        _print_err(f"连接失败: {err_type}: {msg[:120]}")
        if hint:
            print(hint)
        else:
            print("\n  可尝试: uiu model --set-base-url <服务地址> 或 uiu model 重新选择 provider")
        return 1


# ---------- config (secrets + workspace) ----------

def _resolve_key_env(ws: Path, cfg) -> str:
    """Determine the env var name for the API key.

    Order: model.api_key_env > provider profile's api_key_env > OPENAI_API_KEY.
    """
    key = (cfg.model.api_key_env or "").strip()
    if key:
        return key
    try:
        from .providers import get_profile, load_builtin_profiles
        load_builtin_profiles()
        prof = get_profile(cfg.model.provider)
        if prof and prof.api_key_env:
            return prof.api_key_env
    except Exception:
        pass
    return "OPENAI_API_KEY"


def cmd_config(args) -> int:
    ws = _workspace(args)

    if getattr(args, "color", None):
        cfg = load_config(ws)
        name, _, value = str(args.color).partition("=")
        name, value = name.strip(), value.strip()
        try:
            from .app.theme import COLOR_FIELDS
        except Exception:
            COLOR_FIELDS = ()
        if COLOR_FIELDS and name not in COLOR_FIELDS:
            _print_err(f"unknown color slot: {name}（可选：{', '.join(COLOR_FIELDS)}）")
            return 2
        if not name:
            _print_err("format: --color primary=#RRGGBB（清空用 --color primary=）")
            return 2
        if value:
            try:
                from textual.color import Color
                Color.parse(value)
            except Exception:
                _print_err(f"invalid color: {value}（示例：--color primary=#4C9AFF 或 red）")
                return 2
        prefs = dict(getattr(cfg, "tui", {}) or {})
        colors = dict(prefs.get("colors") or {})
        if value:
            colors[name] = value
        else:
            colors.pop(name, None)
        prefs["colors"] = colors
        cfg.tui = prefs
        save_config(ws, cfg)
        msg = f"TUI 配色 {name} = {value}" if value else f"TUI 配色 {name} 已清除"
        _print_ok(msg)
        return 0

    if getattr(args, "theme", None):
        cfg = load_config(ws)
        want = str(args.theme).strip()
        try:
            from .app.theme import THEMES, theme_names
            names = theme_names()
        except Exception:
            names = []
        if names and want not in THEMES:
            _print_err(f"unknown theme: {want}（可选：{', '.join(names)}）")
            return 2
        prefs = dict(getattr(cfg, "tui", {}) or {})
        prefs["theme"] = want
        cfg.tui = prefs
        save_config(ws, cfg)
        _print_ok(f"TUI 主题设为 {want}（下次启动生效；TUI 内 Ctrl+T 可即时切换）")
        return 0

    if getattr(args, "agent_name", ""):
        cfg = load_config(ws)
        cfg.agent_name = args.agent_name.strip()[:32]
        save_config(ws, cfg)
        _print_ok(f"agent 名字改为 {cfg.agent_name}（TUI 里即时生效）")
        return 0

    if args.api_key:
        # route to .env using model's api_key_env key (with sensible fallback)
        cfg = load_config(ws)
        key = _resolve_key_env(ws, cfg)
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[key] = args.api_key
        write_env_file(env_path, existing)
        os.environ[key] = args.api_key  # 立即生效
        _print_ok(f"已写入 {key} 到 {env_path}")
        return 0

    if args.set_secret:
        key, _, value = args.set_secret.partition("=")
        if not value:
            _print_err("格式: KEY=VALUE")
            return 2
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        existing[key.strip()] = value
        write_env_file(env_path, existing)
        os.environ[key.strip()] = value  # 立即生效
        _print_ok(f"已设置 {key.strip()} 到 {env_path}")
        return 0

    if args.unset_secret:
        env_path = ws / ".env"
        existing = parse_env_file(env_path)
        if args.unset_secret in existing:
            del existing[args.unset_secret]
            # overwrite=True so removed keys stay removed (write_env_file merges otherwise)
            write_env_file(env_path, existing, overwrite=True)
            os.environ.pop(args.unset_secret, None)
            _print_ok(f"已清除 {args.unset_secret}")
        return 0

    if args.list:
        env_path = ws / ".env"
        for k, v in sorted(parse_env_file(env_path).items()):
            shown = v if args.show_values else (v[:4] + "…" + v[-2:] if len(v) > 10 else "(set)")
            print(f"  {k} = {shown}")
        # 密钥列表本身不依赖 config.yaml，但配置坏掉时不能假装一切正常：
        # 静默返回 0 会让人以为配置没问题（与 uiu show 的 rc=2 行为也不一致）。
        if config_yaml_path(ws).exists():
            try:
                load_config(ws)
            except Exception as exc:
                _print_err(f"config.yaml 无法解析，请先修复（uiu doctor --fix）：{exc}")
                return 2
        return 0

    print("usage: uiu config [--api-key KEY | --set-secret K=V | --unset-secret K | "
          "--list | --agent-name NAME | --theme NAME | --color SLOT=#RRGGBB]")
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
        # 真重载：重新掃磁盘 skills 并计数（下次对话 load_workspace 本来就会读盘，
        # 这里提前验证，坏文件立刻报错而不是拖死下次启动）
        try:
            from .workspace import load_workspace as _load_ws
            ws_obj = _load_ws(ws)
            print(f"[ok] skills 已重新加载（{len(ws_obj.skills)} 个，下次对话生效）")
        except Exception as e:
            _print_err(f"skills 重载失败: {type(e).__name__}: {e}")
            return 1
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
            _print_err(f"技能已存在: {target}")
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
        _print_ok(f"已创建 {target / 'SKILL.md'}")
        print("edit it, then it'll be picked up on next `uiu` start")
        return 0

    if args.action == "edit":
        target = skills_dir / args.name / "SKILL.md"
        if not target.exists():
            _print_err(f"没有这个技能: {args.name}")
            return 2
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
        try:
            subprocess.run([editor, str(target)], check=False)
        except FileNotFoundError:
            _print_err(f"找不到编辑器 '{editor}'，请设置 $EDITOR")
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
            _print_err(f"渠道名已存在: {name}")
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
        _print_ok(f"已添加渠道 '{name}' [{ctype}]")
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
        elif ctype == "whatsapp":
            print("  WhatsApp: uiu channel add 需带 -o phone_id=... [-o verify=...]")
            print("          uiu config --set-secret WHATSAPP_TOKEN=...（Meta 后台配回调到 /whatsapp）")
        elif ctype == "email":
            print("  邮箱: uiu channel add 需带 -o imap=... -o smtp=... -o user=...")
            print("        uiu config --set-secret EMAIL_PASSWORD=...（建议用应用专用密码）")
        elif ctype == "webhook":
            print("  通用 webhook: 可带 -o secret=... -o chat_field=user.id -o text_field=message")
            print("          外部系统 POST 到 http://0.0.0.0:8765/generic/<name>")
        print("  启用: uiu channel enable", name)
        print("  启动网关: uiu serve")
        return 0

    if args.action == "enable" or args.action == "disable":
        c = cfg.channel(args.name)
        if not c:
            _print_err(f"未知渠道: {args.name}")
            return 2
        c.enabled = (args.action == "enable")
        save_config(ws, cfg)
        _print_ok(f"已{{'启用' if args.action == 'enable' else '停用'}} {args.name}")
        return 0

    if args.action == "remove":
        victim = cfg.channel(args.name)
        cfg.channels = [c for c in cfg.channels if c.name != args.name]
        save_config(ws, cfg)
        if victim is not None:            # 配置改动也能撤销（回收站里存的是渠道定义）
            try:
                import dataclasses

                from .trash import add_record
                add_record(ws, "channel", dataclasses.asdict(victim), label=args.name)
            except Exception:
                pass
        _print_ok(f"removed {args.name}（已移入回收站，uiu trash 可恢复）")
        return 0

    if args.action == "test":
        c = cfg.channel(args.name)
        if not c:
            _print_err(f"未知渠道: {args.name}")
            return 2
        token = c.resolved_token()
        if not token:
            _print_err(f"{c.secret_env} 未设置（.env 或环境变量）；可运行: uiu config --set-secret {c.secret_env}=...")
            return 2
        # dispatch to adapter
        try:
            from . import channels
            ok, msg = channels.test(c)
        except Exception as e:
            _print_err(f"测试失败: {type(e).__name__}: {e}")
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
        "email": "EMAIL_PASSWORD",
        "webhook": "WEBHOOK_SECRET",
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

def _is_git_source_install() -> bool:
    """True when running from a git checkout (dev mode). PyPI/npm installs aren't."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    return (repo_root / ".git").exists() or (repo_root / "src").is_dir()


def cmd_update(args) -> int:
    ws = _workspace(args)
    if args.what == "self":
        if not _is_git_source_install():
            # PyPI / npm 安装：无 git 仓库，直接 pip 升级当前环境
            import importlib.metadata as _md
            try:
                cur = _md.version("uiu")
            except Exception:
                cur = "?"
            from .cli_io import step
            idx = os.environ.get("UIU_PIP_INDEX", "")
            cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--quiet",
                   "--disable-pip-version-check", "uiu"]
            if idx:
                cmd += ["-i", idx]
            with step(f"从 PyPI 升级 uiu（当前 {cur}）"):
                r = subprocess.run(cmd, check=False)
                if r.returncode != 0:
                    _print_err("pip 升级失败（网络/镜像问题？）")
                    return 1
            try:
                new = _md.version("uiu")
            except Exception:
                new = "?"
            _print_ok(f"更新完成 {cur} → {new}，重启 uiu 生效")
            print("  (npm 安装时也可用: npm update -g uiu)")
            return 0
        if getattr(args, "no_pull", False):
            # skip git pull, still verify + staged install
            from .safe_update import staged_install, ensure_backup_point
            import os
            repo_root = Path(__file__).resolve().parent.parent.parent
            src_dir = repo_root / "src" / "uiu"
            tag = ensure_backup_point(repo_root)
            if tag:
                print(f"· 已创建回滚点: git tag {tag}")
            print("· 在隔离环境验证安装（不碰当前运行环境）…")
            ok, msg = staged_install(repo_root, src_dir)
            if not ok:
                _print_err(f"更新验证失败，已回滚（当前环境未动）:\n{msg}")
                return 1
            print(f"· 验证通过 ({msg})，应用更新…")
            rc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", str(repo_root), "--quiet"],
                check=False,
            )
            if rc.returncode != 0:
                _print_err("应用更新失败")
                return 1
            _print_ok("更新完成！重启 uiu 生效")
            return 0
        from .safe_update import safe_self_update
        return safe_self_update()
    if args.what == "skills":
        return _update_default_skills(ws)
    return 2


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
    _print_ok(f"已同步 {copied} 个内置技能到 {target}")
    return 0


# ---------- serve (gateway) ----------

def cmd_serve(args) -> int:
    ws = _workspace(args)
    cfg = load_config(ws)
    from .gateway import Gateway
    from .workspace import load_workspace
    ws_obj = load_workspace(ws)
    gw = Gateway(cfg, ws_obj)
    gw.run(port=args.port, host=getattr(args, "host", "") or "")
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
            _print_err(f"插件已存在: {d}")
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
        _print_ok(f"已创建插件: {d}")
        print("  edit __init__.py, then run `uiu model` to see it")
        return 0

    return 2


# ---------- publish ----------


def _verify_version_consistency() -> tuple[bool, str]:
    """pyproject.toml vs src/uiu/__init__.py must agree (v1.0 publish gate)."""
    import tomllib
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent.parent.parent  # src/uiu -> repo root
    pyproject = here / "pyproject.toml"
    init = here / "src" / "uiu" / "__init__.py"
    if not pyproject.exists() or not init.exists():
        return False, f"cannot locate repo files ({pyproject}, {init})"
    try:
        with open(pyproject, "rb") as f:
            py_ver = tomllib.load(f)["project"]["version"]
    except Exception as e:
        return False, f"pyproject.toml unreadable: {e}"
    txt = init.read_text(encoding="utf-8")
    import re as _re
    m = _re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", txt)
    if not m:
        return False, "src/uiu/__init__.py missing __version__"
    if m.group(1) != py_ver:
        return False, f"version mismatch: pyproject={py_ver} vs __init__={m.group(1)}"
    return True, py_ver


def cmd_publish(args) -> int:
    """Build wheel + sdist and upload to PyPI (or TestPyPI with --test).

    --dry-run: build + inspect wheel contents locally, upload nothing.
    """
    dry_run = bool(getattr(args, "dry_run", False))

    # version-consistency gate (v1.0 release discipline)
    ok, ver = _verify_version_consistency()
    if not ok:
        _print_err(f"发布被拦下: {ver}")
        print("  fix version mismatch, then retry")
        return 2
    print(f"· version consistency ok ({ver})")

    token = args.token or os.environ.get("PYPI_TOKEN") or os.environ.get("TWINE_PASSWORD")
    if not token and not dry_run:
        _print_err("没有 PyPI token：设置 PYPI_TOKEN 环境变量，或用 --token <token> 传入")
        print("  create one at https://pypi.org/manage/account/token/")
        return 2

    # 1. build（慢步骤给进度与耗时，脚本模式下进度走 stderr）
    from .cli_io import step

    with step("安装构建工具 build/twine"):
        rc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "build", "twine"],
            check=False,
        )
        if rc.returncode != 0:
            _print_err("安装构建依赖 build/twine 失败")
            return 1
    with step("构建 sdist + wheel"):
        rc = subprocess.run([sys.executable, "-m", "build", "--sdist", "--wheel"], check=False)
        if rc.returncode != 0:
            _print_err("构建失败 —— 先修上面的错误再重试")
            return 1

    # inspect built artifacts (ensure default workspace/skills packaged)
    dist_dir = Path("dist")
    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        _print_err("dist/ 里没有产出 wheel")
        return 1
    wheel = wheels[-1]
    print(f"· built {wheel.name}")
    if dry_run:
        import zipfile
        names = []
        with zipfile.ZipFile(wheel) as zf:
            names = sorted(n for n in zf.namelist() if not n.startswith("uiu-"))
        want = ["uiu/_default_workspace/SOUL.md", "uiu/_default_workspace/IDENTITY.md"]
        missing = [w for w in want if not any(n.endswith(w.split('/', 1)[1]) for n in names)]
        print(f"· wheel contains {len(names)} files")
        if missing:
            print("  WARNING missing from wheel:", missing)
        else:
            print("  ok: default workspace bundled")
        print("· dry-run complete — nothing uploaded")
        return 0

    # 2. upload
    if args.test:
        repo = "https://test.pypi.org/legacy/"
        print(f"· uploading to TestPyPI…")
    else:
        repo = "https://upload.pypi.org/legacy/"
        print(f"· uploading to PyPI…")

    # expand dist/* glob explicitly (filtered by current version)
    dist_dir = Path("dist")
    artifacts = sorted(dist_dir.glob(f"*{ver}*.whl")) + sorted(dist_dir.glob(f"*{ver}*.tar.gz"))
    if not artifacts:
        _print_err("dist/ 里没有构建产物")
        return 1
    upload_env = {
        **os.environ,
        "TWINE_USERNAME": "__token__",
        "TWINE_PASSWORD": token,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "twine",
            "upload",
            "--repository-url",
            repo,
            *map(str, artifacts),
            "--non-interactive",
            "--disable-progress-bar",
        ],
        env=upload_env,
        check=False,
    )
    if rc.returncode != 0:
        _print_err("上传失败 —— 先修上面的错误再重试")
        return 1

    if args.test:
        print("  done! try: pip install --index-url https://test.pypi.org/simple/ uiu")
    else:
        print("  done! try: pip install uiu   or   pipx run uiu")
    return 0


# ---------- cron ----------

def cmd_cron(args) -> int:
    from . import cron as _cron
    ws = _workspace(args)
    action = args.action

    if action == "list":
        jobs = _cron.load_jobs(ws)
        if not jobs:
            print("(no cron jobs)")
            print("  add: uiu cron add <name> <30m|2h|daily 09:00> \"<task>\"")
            return 0
        import time as _t
        for j in jobs:
            nxt = _t.strftime("%m-%d %H:%M", _t.localtime(j["next_run"])) if j.get("next_run") else "-"
            flag = "on" if j.get("enabled") else "off"
            kind = "[shell]" if j.get("run_shell") else ""
            print(f"  {j['name']:<20} [{flag}] {j['schedule']:<16} 下次{nxt}  {kind} id={j['id']}")
            print(f"    {j['task'][:100]}")
        return 0

    if action == "add":
        try:
            job = _cron.add_job(ws, args.name, args.schedule, args.task, run_shell=getattr(args, "shell", False))
        except ValueError as e:
            _print_err(str(e))
            return 2
        kind = "shell 命令" if job.get("run_shell") else "agent 任务"
        _print_ok(f"已添加 {job['id']}（{args.name} @ {args.schedule}）")
        print("  serve 运行时每 60s 自动 tick；手动跑: uiu cron run", args.name)
        return 0

    if action == "remove":
        job = next((j for j in _cron.load_jobs(ws)
                    if j["id"] == args.name or j["name"] == args.name), None)
        if _cron.remove_job(ws, args.name):
            if job is not None:
                try:
                    from .trash import add_record
                    add_record(ws, "cron_job", job, label=job.get("name", ""))
                except Exception:
                    pass
            _print_ok(f"removed {args.name}（已移入回收站，uiu trash 可恢复）")
            return 0
        _print_err(f"没有这个定时任务: {args.name}")
        return 2

    if action in ("enable", "disable"):
        if _cron.set_enabled(ws, args.name, action == "enable"):
            _print_ok(f"{args.name} 已{{'启用' if action == 'enable' else '停用'}}")
            return 0
        _print_err(f"没有这个定时任务: {args.name}")
        return 2

    if action == "run":
        jobs = [j for j in _cron.load_jobs(ws) if j["id"] == args.name or j["name"] == args.name]
        if not jobs:
            _print_err(f"没有这个定时任务: {args.name}")
            return 2
        out = _cron.run_job(ws, jobs[0])
        _print_ok(f"已执行 → {out}")
        return 0

    if action == "tick":
        ran = _cron.tick(ws)
        _print_ok(f"tick: 执行了 {len(ran)} 个任务")
        for out in ran:
            print(f"  {out}")
        return 0

    return 2


# ---------- sessions ----------

def cmd_sessions(args) -> int:
    from . import sessions as _sessions
    ws = _workspace(args)
    action = args.action

    if action == "list":
        from . import cli_io

        items = _sessions.list_sessions(ws)
        usage = _sessions.sessions_usage(ws)
        over = _session_cap(ws)
        data = {"count": usage["count"], "bytes": usage["bytes"], "cap": over,
                "sessions": [{k: s.get(k) for k in ("id", "turns", "bytes", "updated")}
                             for s in items]}
        if not items:
            cli_io.result("sessions.list", data=data,
                          human="(no saved sessions — TUI 里 /save 存一个)")
            return 0
        import time as _t
        lines = []
        for s in items:
            ts = _t.strftime("%m-%d %H:%M", _t.localtime(s["updated"]))
            kb = s.get("bytes", 0) / 1024
            lines.append(f"  {s['id']:<24} {s['turns']:>3} 轮  {kb:>7.1f} KB  {ts}")
        note = f"（上限 {over}，建议 uiu sessions prune）" if over and usage["count"] > over else ""
        lines.append(f"\n  共 {usage['count']} 个 · {usage['bytes'] / 1024 / 1024:.1f} MB {note}")
        cli_io.result("sessions.list", data=data, human="\n".join(lines))
        return 0

    if action == "usage":
        from . import cli_io

        usage = _sessions.sessions_usage(ws)
        over = _session_cap(ws)
        data = {"count": usage["count"], "bytes": usage["bytes"], "cap": over,
                "newest": usage["newest"], "oldest": usage["oldest"],
                "largest": [{"id": r["id"], "bytes": r.get("bytes", 0)}
                            for r in usage["largest"]]}
        if not usage["count"]:
            cli_io.result("sessions.usage", data=data, human="(还没有已保存的会话)")
            return 0
        lines = [f"  会话数: {usage['count']}",
                 f"  占用:   {usage['bytes'] / 1024 / 1024:.2f} MB",
                 f"  最新:   {usage['newest']}",
                 f"  最旧:   {usage['oldest']}",
                 "  最大的几个："]
        lines += [f"    {row['id']:<24} {row.get('bytes', 0) / 1024:>8.1f} KB"
                  for row in usage["largest"]]
        if over and usage["count"] > over:
            lines.append(f"\n  已超过上限 {over}：uiu sessions prune --keep {over}"
                         "（会进回收站，可恢复）")
        cli_io.result("sessions.usage", data=data, human="\n".join(lines))
        return 0

    if action == "prune":
        from . import cli_io

        keep = getattr(args, "keep", None)
        days = getattr(args, "days", None)
        usage = _sessions.sessions_usage(ws)
        # 默认值来自配置，命令行优先
        if keep is None:
            keep = _session_cap(ws)
        if days is None:
            days = _session_age_days(ws)
        plan = _sessions.prune_sessions(ws, keep=int(keep or 0),
                                        max_age_days=float(days or 0),
                                        protect=("default",),
                                        dry_run=True)
        if not plan["removed"]:
            cli_io.result("sessions.prune", data={**plan, "applied": False},
                          human=f"(无需裁剪：共 {usage['count']} 个会话，keep={keep}, days={days})")
            return 0
        head = (f"将裁剪 {len(plan['removed'])} 个会话"
                f"（释放约 {plan['freed'] / 1024:.1f} KB）：")
        listing = "\n".join(f"  - {sid}" for sid in plan["removed"][:20])
        if len(plan["removed"]) > 20:
            listing += f"\n  … 其余 {len(plan['removed']) - 20} 个"

        # JSON 模式不交互：没有 --yes 就只出计划（脚本自己决定要不要真删）
        if getattr(args, "dry_run", False) or (cli_io.json_mode()
                                               and not getattr(args, "yes", False)):
            cli_io.result("sessions.prune", data={**plan, "applied": False},
                          human=f"{head}\n{listing}\n\n(dry-run：没有真的删除)")
            return 0
        if not cli_io.json_mode() and not getattr(args, "yes", False) \
                and not _confirm("确认裁剪？", default_yes=False):
            cli_io.result("sessions.prune", ok=False, data={**plan, "applied": False},
                          error="用户取消", human="已取消")
            return 0
        result = _sessions.prune_sessions(ws, keep=int(keep or 0),
                                          max_age_days=float(days or 0),
                                          protect=("default",))
        cli_io.result("sessions.prune", data={**result, "applied": True},
                      human=f"{head}\n{listing}\n\n"
                            f"[ok] 已裁剪 {len(result['removed'])} 个会话"
                            "（进回收站，uiu trash 可恢复）")
        return 0

    if action == "show":
        msgs = _sessions.load_session(ws, args.name)
        if msgs is None:
            _print_err(f"没有这个会话: {args.name}")
            return 2
        for m in msgs[-20:]:
            role = m.get("role", "?")
            content = m.get("content", "")
            content = content if isinstance(content, str) else "(non-text)"
            print(f"[{role}] {content[:300]}")
        return 0

    if action == "search":
        hits = _sessions.search_sessions(ws, args.query, limit=args.limit)
        if not hits:
            print("(no matches in saved sessions)")
            return 0
        for h in hits:
            print(f"[{h['session']} · {h['role']}] {h['text'][:600]}")
            for c in h.get("context", []):
                print(f"    · ({c['role']}) {c['text'][:200]}")
        return 0

    if action == "remove":
        if _sessions.remove_session(ws, args.name):
            _print_ok(f"已删除 {args.name}")
            return 0
        _print_err(f"没有这个会话: {args.name}")
        return 2

    return 2


# ---------- doctor (OpenClaw-style diagnose & fix) ----------

def cmd_doctor(args) -> int:
    import dataclasses

    from . import cli_io
    from .doctor import _all_checks, run_doctor
    ws = _workspace(args)
    kwargs = {"lint": getattr(args, "lint", False),
              "fix": getattr(args, "fix", False),
              "yes": getattr(args, "yes", False),
              "install_deps": getattr(args, "install_deps", False)}
    if not cli_io.json_mode():
        return run_doctor(ws, **kwargs)

    # JSON 模式：人读过程走 stderr，stdout 只留一个信封
    rc = run_doctor(ws, out=cli_io.progress, **kwargs)
    findings = [dataclasses.asdict(f) for f in _all_checks(ws)]
    cli_io.result("doctor", ok=(rc == 0),
                  data={"findings": findings, "exit_code": rc, **kwargs},
                  error="" if rc == 0 else "存在未解决的问题")
    return rc


# ---------- macro (keyboard-macro style record/play) ----------

def cmd_macro(args) -> int:
    from . import macros as _macros
    ws = _workspace(args)
    action = args.action

    if action == "list":
        print(_macros.macro_list())
        return 0

    if action == "record":
        if not getattr(args, "yes", False):
            print("录制将真实捕获你的鼠标键盘操作。准备就绪后开始：")
            print("  · 切到目标窗口")
            print("  · 按 F9 结束录制")
            try:
                ans = input("开始录制？[Y/n] ").strip().lower()
            except EOFError:
                ans = "y"
            if ans not in ("", "y", "yes"):
                print("(取消)")
                return 0
        from .macro_recorder import MacroRecorder, macros_dir, save_macro
        import re as _re
        safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", args.name.strip()).strip("_")[:64]
        if not safe:
            _print_err("宏名非法")
            return 2
        path = macros_dir(ws) / f"{safe}.json"
        print(f"· 录制中…（按 F9 停止，--timeout 可设自动停止）")
        rec = MacroRecorder(timeout=max(0, min(args.timeout or 0, 1800)))
        try:
            steps, aborted = rec.run()
        except Exception as e:
            _print_err(f"录制失败: {type(e).__name__}: {e}")
            return 1
        if not steps:
            print("(未捕获到操作，未保存)")
            return 0
        save_macro(path, safe, getattr(args, "desc", "") or "", steps)
        _print_ok(f"已录制宏 '{safe}'：{len(steps)} 步（{'F9 停止' if aborted else '超时自动停'}）→ {path.name}")
        print("  回放: uiu macro play", safe)
        return 0

    if action == "play":
        from .macro_recorder import load_macro
        import re as _re
        safe = _re.sub(r"[^a-zA-Z0-9_-]", "_", args.name.strip()).strip("_")[:64]
        path = ws / "macros" / f"{safe}.json"
        if not path.exists():
            _print_err(f"宏不存在: {safe}")
            return 2
        try:
            macro = load_macro(path)
        except Exception as e:
            _print_err(f"宏文件损坏: {e}")
            return 2
        steps = macro.get("steps", [])
        print(f"宏 '{safe}': {len(steps)} 步 — {macro.get('description', '')}")
        if not getattr(args, "yes", False):
            print("回放将真实控制鼠标键盘。请确保目标窗口已就绪。")
            print("  · 甩鼠标到屏幕左上角 或 按 F9 可紧急中止")
            try:
                ans = input(f"回放 {len(steps)} 步？[Y/n] ").strip().lower()
            except EOFError:
                ans = "y"
            if ans not in ("", "y", "yes"):
                print("(取消)")
                return 0
        from .macro_player import play_steps
        played, status = play_steps(
            steps, speed=max(0.1, float(args.speed or 1.0)),
            start=args.start, end=args.end or None)
        print(f"{status}（{played}/{len(steps)} 步）")
        return 0

    if action == "quick":
        from .quick_macro import QuickMacroDaemon
        import time as _t
        print("╭────────────────────────────────────────────────────────╮")
        print("│  ⚡ uiu 极速按键精灵 (Quick Macro)                     │")
        print("│                                                        │")
        print("│  [F10]      开始录制 / 结束录制（保存为循环宏）         │")
        print("│  [F12]      单次回放刚才录制的动作                     │")
        print("│  [Ctrl+F12] 连续循环 10 次                             │")
        print("│  [F11]      紧急刹车 / 强制中止                        │")
        print("│                                                        │")
        print("│  提示：操作全程伴随系统蜂鸣音提示，无需切回本终端。     │")
        print("│  按 Ctrl+C 退出精灵守护模式。                          │")
        print("╰────────────────────────────────────────────────────────╯")
        daemon = QuickMacroDaemon(ws, on_status_change=lambda st, msg: print(f"  [{st}] {msg}"))
        daemon.start()
        try:
            while True:
                _t.sleep(0.5)
        except KeyboardInterrupt:
            print("\n· 正在退出按键精灵守护...")
        finally:
            daemon.stop()
            print("[ok] 已退出")
        return 0

    if action == "remove":
        from . import macros as _macros_mod
        out = _macros_mod.macro_remove(args.name)
        print(out)
        return 0 if out.startswith("[ok]") else 2

    return 2


def cmd_quick(args) -> int:
    """Shortcut entry for uiu quick."""
    setattr(args, "action", "quick")
    return cmd_macro(args)


# ---------- daemon ----------

def cmd_daemon(args) -> int:
    from . import daemon as _daemon
    ws = _workspace(args)
    action = args.action

    if action == "start":
        ok, msg = _daemon.start_daemon(ws)
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "stop":
        ok, msg = _daemon.stop_daemon()
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "status":
        info = _daemon.status_daemon(ws)
        if info["running"]:
            _print_ok(f"守护进程运行中 (PID: {info['pid']})")
        else:
            print("守护进程未运行 (未启动)")
        print(f"  工作目录: {info['workspace']}")
        print(f"  日志文件: {info['log_path']}")
        print(f"  定时任务: 共 {info['total_jobs']} 个，已启用 {info['enabled_jobs']} 个")
        if info["jobs"]:
            import time as _t
            for j in info["jobs"]:
                nxt = _t.strftime("%m-%d %H:%M", _t.localtime(j["next_run"])) if j.get("next_run") else "-"
                flag = "on" if j.get("enabled") else "off"
                kind = "[shell]" if j.get("run_shell") else "[agent]"
                print(f"    - {j['name']:<18} [{flag}] {j['schedule']:<12} 下次: {nxt} {kind}")
        return 0

    if action == "run":
        interval = getattr(args, "interval", 60)
        print(f"[daemon] 正在前台运行定时任务循环（每 {interval} 秒检查一次）... 按 Ctrl+C 退出")
        _daemon.run_daemon(ws, interval=interval)
        return 0

    if action == "install-autostart":
        ok, msg = _daemon.install_autostart(ws)
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    if action == "uninstall-autostart":
        ok, msg = _daemon.uninstall_autostart()
        if ok:
            _print_ok(msg)
            return 0
        else:
            _print_err(msg)
            return 2

    return 2

# ---------- backup / restore（审计 §3.4） ----------

def cmd_backup(args) -> int:
    """把 workspace 关键文件打包；默认滚动保留最近 N 份。"""
    import time as _time

    ws = _workspace(args)
    from .backup import backup_dir, create_backup, list_backups

    from . import cli_io

    if getattr(args, "list", False):
        items = list_backups(ws)
        data = {"dir": str(backup_dir(ws)),
                "backups": [{"name": p.name, "bytes": p.stat().st_size,
                             "mtime": p.stat().st_mtime} for p in items]}
        if not items:
            cli_io.result("backup.list", data=data,
                          human="(还没有备份 —— 运行 uiu backup 立刻做一份)")
            return 0
        listing = "\n".join(
            f"  {p.name}   {p.stat().st_size / 1024:8.1f} KB   "
            f"{_time.strftime('%Y-%m-%d %H:%M', _time.localtime(p.stat().st_mtime))}"
            for p in items)
        cli_io.result("backup.list", data=data,
                      human=f"{listing}\n\n目录: {backup_dir(ws)}")
        return 0

    to = getattr(args, "to", "") or None
    keep = getattr(args, "keep", 7)
    try:
        path = create_backup(ws, to=to, keep=None if to else keep, note="manual")
    except OSError as exc:
        cli_io.result("backup", ok=False, error=str(exc), human=f"[error] 备份失败: {exc}")
        return 2
    has_env = (ws / ".env").exists()
    lines = [f"[ok] 已备份 → {path}", f'  恢复: uiu restore "{path}"']
    if has_env:
        lines.append("  注意：备份包含 .env（里面有 API key），请当密钥文件保管")
    cli_io.result("backup", data={"path": str(path), "bytes": path.stat().st_size,
                                  "contains_env": has_env},
                  human="\n".join(lines))
    return 0


def cmd_restore(args) -> int:
    """从备份恢复；恢复前自动做一份 pre-restore 快照，可撤销。"""
    ws = _workspace(args)
    from .backup import restore_backup

    archive = Path(str(getattr(args, "archive", ""))).expanduser()
    if not archive.is_file():
        _print_err(f"找不到备份文件: {archive}")
        return 2

    if not getattr(args, "yes", False):
        print(f"将用 {archive.name} 覆盖当前 workspace: {ws}")
        print("（恢复前会自动做一份 pre-restore 备份，可撤销）")
        if not _confirm("确认恢复？", default_yes=False):
            print("已取消")
            return 0

    try:
        result = restore_backup(ws, archive, keep=getattr(args, "keep", 7))
    except ValueError as exc:
        _print_err(str(exc))            # zip-slip 等越界内容
        return 2
    except Exception as exc:
        _print_err(f"恢复失败: {type(exc).__name__}: {exc}")
        return 2

    _print_ok(f"已恢复 {len(result.get('restored', []))} 个文件")
    if result.get("safety_backup"):
        print(f"  恢复前快照: {result['safety_backup']}")
    print("  提示：重启 uiu 让新配置生效")
    return 0


# ---------- audit（工具执行审计日志，审计 §5.6） ----------

def cmd_audit(args) -> int:
    import json as _json

    ws = _workspace(args)
    from .audit import audit_path, read_events

    from . import cli_io

    events = read_events(ws, tail=int(getattr(args, "tail", 30) or 30))
    if not events:
        cli_io.result("audit", data={"events": [], "path": str(audit_path(ws))},
                      human=f"(还没有审计记录 — 工具执行后写入 {audit_path(ws)})")
        return 0

    if cli_io.json_mode():
        cli_io.result("audit", data={"events": events, "path": str(audit_path(ws))})
        return 0

    for event in events:
        when = event.get("time", "")
        kind = event.get("event", "?")
        tool = event.get("tool", "")
        status = event.get("status") or event.get("decision") or ""
        ms = event.get("ms")
        detail = str(event.get("detail") or event.get("reason") or "")[:70]
        timing = f" {ms}ms" if isinstance(ms, int) and ms else ""
        print(f"  {when}  {kind:<12} {tool:<18} {status:<10}{timing}  {detail}")
    cli_io.progress(f"\n共 {len(events)} 条 · {audit_path(ws)}")
    return 0


def _session_cap(ws) -> int:
    """会话数量上限（配置里 sessions_keep；<=0 表示不限）。"""
    try:
        return int(getattr(load_config(ws), "sessions_keep", 200) or 0)
    except Exception:
        return 200


def _session_age_days(ws) -> float:
    try:
        return float(getattr(load_config(ws), "sessions_max_age_days", 0.0) or 0.0)
    except Exception:
        return 0.0


# ---------- trash（回收站，审计 §4.1） ----------

def cmd_trash(args) -> int:
    from . import cli_io

    ws = _workspace(args)
    from .trash import DEFAULT_KEEP_DAYS, describe, list_entries, purge, restore

    if getattr(args, "restore", ""):
        ok, msg = restore(ws, str(args.restore))
        cli_io.result("trash.restore", ok=ok, data={"id": args.restore} if ok else None,
                      error="" if ok else msg, human=msg)
        return 0 if ok else 2

    if getattr(args, "purge", False):
        days = float(getattr(args, "days", DEFAULT_KEEP_DAYS) or 0)
        removed = purge(ws, days=days)
        human = (f"[ok] 已清理 {len(removed)} 项：{', '.join(removed)}" if removed
                 else "(没有超过时限的回收站条目)")
        cli_io.result("trash.purge", data={"removed": removed, "days": days}, human=human)
        return 0

    entries = list_entries(ws)
    data = {"count": len(entries),
            "entries": [{k: e.get(k) for k in ("id", "kind", "label", "origin", "created")}
                        for e in entries]}
    if not entries:
        cli_io.result("trash.list", data=data,
                      human="(回收站是空的 — 删除会话/宏/渠道/定时任务会先移到这里)")
        return 0
    listing = "\n".join("  " + describe(entry) for entry in entries)
    cli_io.result("trash.list", data=data,
                  human=f"{listing}\n\n共 {len(entries)} 项 · 恢复: uiu trash --restore <id>"
                        " · 清理: uiu trash --purge")
    return 0
