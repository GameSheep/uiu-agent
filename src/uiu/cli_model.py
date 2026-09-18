"""模型与配置：model / config / plugins（含 provider 向导与连接测试）（自原 commands.py 按域拆分；审计 §2.1）。"""

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

from .cli_shared import (
    _plugins_dir,
    _print_err,
    _print_ok,
    _workspace,
)


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


def _setup_playwright_browsers_async() -> None:
    """Kick off Playwright Chromium install in the background (non-blocking)."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return
    import threading
    print("· 后台安装 Playwright Chromium（不阻塞，可继续使用）…")
    threading.Thread(target=_setup_playwright_browsers, daemon=True).start()
