"""CLI entry: argparse subparsers dispatching to uiu.commands.

Usage:
    uiu                              # start TUI REPL (default)
    uiu init                         # bootstrap workspace + .env
    uiu show                         # print current config
    uiu model [--set-model X]        # view/update model config
    uiu config [--api-key K]         # manage secrets
    uiu skills {list,add,edit,path}  # manage skills
    uiu channel {list,add,...}       # manage channels (telegram, etc.)
    uiu update {self,skills}         # update code or sync default skills
    uiu version
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path | None = None, paths: list[Path] | None = None) -> None:
    """Minimal .env loader — sets only keys not already in environ.

    Searches in order:
      1. explicit path (if given)
      2. explicit paths list (if given)
      3. ./.env
      4. ./workspace/.env
      5. ~/.uiu/workspace/.env
    """
    if paths is None:
        paths = []
        if path is not None:
            paths.append(path)
        paths += [
            Path.cwd() / ".env",
            Path.cwd() / "workspace" / ".env",
            Path.home() / ".uiu" / "workspace" / ".env",
        ]

    seen: set[str] = set()
    for p in paths:
        if not p.exists() or p in seen:
            continue
        seen.add(p)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            os.environ.setdefault(k, v)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uiu",
        description="A minimal personal-IP agent skeleton. Edit workspace/SOUL.md to make it yours.",
    )
    p.add_argument("--workspace", "-w", help="Path to workspace dir (default: ./workspace)")
    p.add_argument("-V", "--version", action="store_true", help="print version and exit")
    p.add_argument("--no-tui", action="store_true", help="use the classic REPL instead of the full-screen app")
    p.add_argument("--skip-setup", action="store_true", help="skip first-run welcome/model wizard (advanced)")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    sub.add_parser("init", help="bootstrap workspace + .env")

    sub.add_parser("show", help="show current config (model, channels, secrets state)")

    # model
    pm = sub.add_parser("model", help="view/switch model interactively (or with --set-*)")
    pm.add_argument("--refresh", action="store_true", help="re-fetch every provider's live /v1/models list (wipe picker cache)")
    pm.add_argument("--set-provider")
    pm.add_argument("--set-base-url")
    pm.add_argument("--set-model")
    pm.add_argument("--set-api-key-env")
    pm.add_argument("--set-temperature", type=float)
    pm.add_argument("--set-max-tokens", type=int)
    pm.add_argument("--set-api-key", help="write API key to .env under current api_key_env")

    # config (secrets)
    pc = sub.add_parser("config", help="manage secrets (API keys, tokens)")
    pc.add_argument("--api-key", help="shortcut: set <model.api_key_env> in .env")
    pc.add_argument("--set-secret", metavar="KEY=VALUE", help="set arbitrary secret in .env")
    pc.add_argument("--unset-secret", metavar="KEY", help="remove a secret from .env")
    pc.add_argument("--list", action="store_true", help="list secrets")
    pc.add_argument("--show-values", action="store_true", help="don't redact values when --list")
    pc.add_argument("--agent-name", help="set agent display name (shown in TUI header/status)")
    pc.add_argument("--theme", help="set TUI theme (uiu-dark / uiu-mono / uiu-neon / uiu-solar)")
    pc.add_argument("--color", help="override one TUI color, e.g. --color primary=#4C9AFF")

    # skills
    psk = sub.add_parser("skills", help="search, install, and manage skills")
    psk_sub = psk.add_subparsers(dest="action", metavar="<action>", required=True)
    psk_sub.add_parser("list", help="list installed skills")
    psk_install = psk_sub.add_parser("install", help="install a skill from GitHub repo or URL")
    psk_install.add_argument("identifier", help="owner/repo | GitHub URL | raw SKILL.md URL")
    psk_install.add_argument("--name", default="", help="override skill name")
    psk_install.add_argument("--force", action="store_true", help="overwrite if exists")
    psk_search = psk_sub.add_parser("search", help="search GitHub for skills")
    psk_search.add_argument("query")
    psk_search.add_argument("--limit", type=int, default=10)
    psk_inspect = psk_sub.add_parser("inspect", help="preview a skill without installing")
    psk_inspect.add_argument("identifier")
    psk_ask = psk_sub.add_parser("add", help="create a new skill from template")
    psk_ask.add_argument("name", help="skill name (will be the directory name)")
    psk_edit = psk_sub.add_parser("edit", help="open SKILL.md in $EDITOR")
    psk_edit.add_argument("name")
    psk_sub.add_parser("reload", help="reload skills from disk (after installing)")
    psk_sub.add_parser("path", help="print skills directory path")

    # channel
    pch = sub.add_parser("channel", help="manage channels (telegram, discord, …)")
    pch_sub = pch.add_subparsers(dest="action", metavar="<action>", required=True)
    pch_sub.add_parser("list", help="list configured channels")
    pch_cha = pch_sub.add_parser("add", help="add a channel")
    pch_cha.add_argument("name", help="unique channel handle")
    pch_cha.add_argument("--type", required=True, help="telegram | discord | …")
    pch_cha.add_argument("--secret-env", help="env var name holding the token (default inferred)")
    pch_cha.add_argument("--option", "-o", action="append", default=[], help="key=value adapter options")
    pch_en = pch_sub.add_parser("enable", help="enable a channel")
    pch_en.add_argument("name")
    pch_dis = pch_sub.add_parser("disable", help="disable a channel")
    pch_dis.add_argument("name")
    pch_rm = pch_sub.add_parser("remove", help="remove a channel")
    pch_rm.add_argument("name")
    pch_test = pch_sub.add_parser("test", help="verify channel credentials (calls platform API)")
    pch_test.add_argument("name")

    # update
    pu = sub.add_parser("update", help="update code or sync bundled skills")
    pu_sub = pu.add_subparsers(dest="what", metavar="<what>", required=True)
    pu_self = pu_sub.add_parser("self", help="git pull + reinstall")
    pu_self.add_argument("--no-pull", action="store_true", help="skip git pull, only reinstall")
    pu_sub.add_parser("skills", help="sync bundled default skills into workspace")

    sub.add_parser("version", help="print version")

    # plugins
    ppl = sub.add_parser("plugins", help="manage provider plugins (~/.uiu/plugins/model-providers/)")
    ppl_sub = ppl.add_subparsers(dest="action", metavar="<action>", required=True)
    ppl_sub.add_parser("list", help="list installed provider plugins")
    ppl_new = ppl_sub.add_parser("new", help="scaffold a new provider plugin from template")
    ppl_new.add_argument("name", help="provider name (directory name)")
    ppl_sub.add_parser("path", help="print plugins directory")

    # serve (gateway)
    pserve = sub.add_parser("serve", help="start gateway: run all enabled channels (telegram/feishu/wecom)")
    pserve.add_argument("--port", type=int, default=8765, help="webhook port for feishu/wecom (default 8765)")
    pserve.add_argument("--host", default="",
                        help="bind address (default 127.0.0.1; 对外暴露前必须先设 UIU_GATEWAY_TOKEN)")

    # publish
    pp = sub.add_parser("publish", help="build & upload to PyPI")
    pp.add_argument("--test", action="store_true", help="publish to TestPyPI")
    pp.add_argument("--dry-run", action="store_true", help="build + inspect wheel locally, upload nothing")
    pp.add_argument("--token", help="PyPI API token (or set env PYPI_TOKEN)")

    # cron
    pcr = sub.add_parser("cron", help="scheduled jobs (tick runs due jobs)")
    pcr_sub = pcr.add_subparsers(dest="action", metavar="<action>", required=True)
    pcr_sub.add_parser("list", help="list jobs")
    pcr_add = pcr_sub.add_parser("add", help="add a job")
    pcr_add.add_argument("name", help="job name")
    pcr_add.add_argument("schedule", help="30m | 2h | 1d | daily 09:00 | 'M H * * *' | once <ISO>")
    pcr_add.add_argument("task", help="agent task prompt to run")
    pcr_add.add_argument("--shell", action="store_true", help="run task as a shell command (no agent, zero tokens)")
    pcr_rm = pcr_sub.add_parser("remove", help="remove a job (id or name)")
    pcr_rm.add_argument("name")
    pcr_en = pcr_sub.add_parser("enable", help="enable a job")
    pcr_en.add_argument("name")
    pcr_dis = pcr_sub.add_parser("disable", help="disable a job")
    pcr_dis.add_argument("name")
    pcr_run = pcr_sub.add_parser("run", help="run a job now (id or name)")
    pcr_run.add_argument("name")
    pcr_sub.add_parser("tick", help="run all due jobs once")

    # sessions
    pse = sub.add_parser("sessions", help="saved conversation sessions")
    pse_sub = pse.add_subparsers(dest="action", metavar="<action>", required=True)
    pse_sub.add_parser("list", help="list saved sessions")
    pse_show = pse_sub.add_parser("show", help="show recent turns of a session")
    pse_show.add_argument("name")
    pse_search = pse_sub.add_parser("search", help="keyword search across saved sessions")
    pse_search.add_argument("query")
    pse_search.add_argument("--limit", type=int, default=5)
    pse_rm = pse_sub.add_parser("remove", help="delete a session")
    pse_rm.add_argument("name")

    # macro
    pmc = sub.add_parser("macro", help="record/play keyboard-mouse macros (keyboard-macro style)")
    pmc_sub = pmc.add_subparsers(dest="action", metavar="<action>", required=True)
    pmc_rec = pmc_sub.add_parser("record", help="record a macro (press F9 to stop)")
    pmc_rec.add_argument("name")
    pmc_rec.add_argument("--desc", default="", help="macro description")
    pmc_rec.add_argument("--timeout", type=int, default=0, help="auto-stop after N seconds (0=wait for F9)")
    pmc_play = pmc_sub.add_parser("play", help="play a macro")
    pmc_play.add_argument("name")
    pmc_play.add_argument("--speed", type=float, default=1.0, help="speed multiplier (2=faster)")
    pmc_play.add_argument("--from", dest="start", type=int, default=0, help="start step (1-based)")
    pmc_play.add_argument("--to", dest="end", type=int, default=0, help="end step (inclusive)")
    pmc_play.add_argument("--yes", action="store_true", help="skip confirmation")
    pmc_sub.add_parser("list", help="list saved macros")
    pmc_sub.add_parser("quick", help="start QuickMacro daemon (F10 record, F12 replay, F11 abort)")
    pmc_rm = pmc_sub.add_parser("remove", help="delete a macro")
    pmc_rm.add_argument("name")

    # quick shortcut
    sub.add_parser("quick", help="shortcut: start QuickMacro daemon (F10 record, F12 replay, F11 abort)")

    # doctor
    pdoc = sub.add_parser("doctor", help="diagnose & fix uiu configuration problems")
    pdoc.add_argument("--lint", action="store_true", help="read-only check, no fixes")
    pdoc.add_argument("--fix", action="store_true", help="apply auto-fixes (prompts per item)")
    pdoc.add_argument("--yes", action="store_true", help="with --fix: apply all without prompting")
    pdoc.add_argument("--install-deps", action="store_true",
                      help="with --fix: really pip install missing optional extras (off by default)")

    # trash（回收站，审计 §4.1）
    ptr = sub.add_parser("trash", help="recycle bin: list / restore / purge deleted items")
    ptr.add_argument("--list", action="store_true", help="list trashed items (default)")
    ptr.add_argument("--restore", default="", help="restore an entry by id")
    ptr.add_argument("--purge", action="store_true", help="delete entries older than --days")
    ptr.add_argument("--days", type=float, default=7.0, help="purge threshold in days (default 7)")

    # audit（工具执行审计日志，审计 §5.6）
    paud = sub.add_parser("audit", help="show the tool-execution audit log")
    paud.add_argument("--tail", type=int, default=30, help="show the newest N events (default 30)")
    paud.add_argument("--json", action="store_true", help="print raw JSONL")

    # backup / restore（用户数据兜底，审计 §3.4）
    pbk = sub.add_parser("backup", help="back up the workspace (config/sessions/memory/skills)")
    pbk.add_argument("--to", default="", help="target dir (default: <workspace>/backups)")
    pbk.add_argument("--keep", type=int, default=7, help="keep the newest N backups (default 7)")
    pbk.add_argument("--list", action="store_true", help="list existing backups and exit")
    prs = sub.add_parser("restore", help="restore a workspace from a backup zip")
    prs.add_argument("archive", help="path to uiu-backup-*.zip")
    prs.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    prs.add_argument("--keep", type=int, default=7, help="keep the newest N backups (default 7)")

    # daemon (background cron service)
    pdm = sub.add_parser("daemon", help="manage background cron daemon and autostart")
    pdm_sub = pdm.add_subparsers(dest="action", metavar="<action>", required=True)
    pdm_sub.add_parser("start", help="start background daemon (zero-window)")
    pdm_sub.add_parser("stop", help="stop running background daemon")
    pdm_sub.add_parser("status", help="show background daemon status and scheduled jobs")
    pdm_run = pdm_sub.add_parser("run", help="run daemon loop in foreground")
    pdm_run.add_argument("--interval", type=int, default=60, help="cron tick interval in seconds (default 60)")
    pdm_sub.add_parser("install-autostart", help="register Windows startup script for boot persistence")
    pdm_sub.add_parser("uninstall-autostart", help="remove Windows startup script")

    return p


def _has_textual() -> bool:
    """True when textual is importable (the full-screen TUI dependency)."""
    try:
        import textual  # noqa: F401
        return True
    except Exception:
        return False


def _tui_available() -> bool:
    """Full-screen TUI only works on an interactive terminal."""
    if not _has_textual():
        return False
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return False
    except Exception:
        return False
    return True


def _run_tui(args, parser: argparse.ArgumentParser) -> int:
    from .config import AppConfig, ModelConfig, load_config
    from .llm import make_client
    from .workspace import load_workspace

    from .commands import _workspace as _ws, cmd_init, cmd_model

    ws_path = _ws(args)

    # First-run UX: welcome banner + guided setup (auto-init + model wizard)
    first_run = not (ws_path / "SOUL.md").exists()
    skip = bool(getattr(args, "skip_setup", False))
    if first_run:
        _print_welcome(ws_path)
        if not skip:
            import argparse as _argparse
            init_ns = _argparse.Namespace(workspace=str(ws_path) if args.workspace else None)
            cmd_init(init_ns)
        else:
            ws_path.mkdir(parents=True, exist_ok=True)

    cfg = load_config(ws_path)

    # First-run UX: no API key -> auto run model wizard (unless --skip-setup)
    needs_key = cfg.model.resolved_api_key() == ""
    if needs_key:
        try:
            from .providers import get_profile, load_builtin_profiles
            load_builtin_profiles()
            prof = get_profile(cfg.model.provider)
            if prof and prof.auth_type == "none":
                needs_key = False  # local providers (ollama/vllm) don't need a key
        except Exception:
            pass

    if needs_key and not skip:
        print("\n[first-run] 还没有配置模型 —— 花一分钟配好就能开聊（本地模型如 Ollama 免 key）")
        import argparse as _argparse
        model_ns = _argparse.Namespace(
            workspace=str(ws_path) if args.workspace else None,
            set_provider=None, set_base_url=None, set_model=None,
            set_api_key_env=None, set_temperature=None, set_max_tokens=None,
            set_api_key=None,
        )
        rc = cmd_model(model_ns)
        if rc != 0:
            return rc
        # re-read config after wizard
        cfg = load_config(ws_path)

    # still no key after wizard? only an error if provider actually needs one
    if not cfg.model.resolved_api_key():
        try:
            from .providers import get_profile, load_builtin_profiles
            load_builtin_profiles()
            prof = get_profile(cfg.model.provider)
            if not (prof and prof.auth_type == "none"):
                print("error: 还没有 API key。运行 `uiu model` 配置，或 `uiu model --set-api-key sk-xxx`", file=sys.stderr)
                return 2
        except Exception:
            print("error: 还没有 API key。运行 `uiu model` 配置，或 `uiu model --set-api-key sk-xxx`", file=sys.stderr)
            return 2

    client = make_client(cfg.model)
    ws = load_workspace(ws_path)

    # 首次配置后：进聊天前做一次连通性测试（可跳过；失败给明确修法）
    if first_run and not skip:
        try:
            from .commands import _test_model_connection
            rc = _test_model_connection(ws_path, cfg)
            if rc != 0:
                print("[warn] 连通性测试未通过 —— 仍可进入界面，但建议先修复模型配置", file=sys.stderr)
        except Exception:
            pass

    # 启动时连接配置的 MCP 服务器（best-effort，失败不影响使用）
    try:
        from .mcp_tools import try_connect_all as _mcp_connect
        for line in _mcp_connect(cfg):
            print(line, flush=True)
    except Exception:
        pass

    # v1.0: default to the full-screen textual app; fall back to the classic
    # REPL when the user passes --no-tui or textual cannot start (e.g. pipe).
    use_classic = bool(getattr(args, "no_tui", False)) or not _tui_available()
    if not use_classic:
        try:
            from .app import run_app
            return run_app(client, ws, model=cfg.model.default, cfg=cfg.model,
                           app_cfg=cfg, theme_name=_tui_theme(cfg))
        except Exception as _tui_err:
            print(f"[warn] full-screen TUI unavailable ({_tui_err}); falling back to REPL", file=sys.stderr)
    from .tui import repl
    return repl(client, ws, model=cfg.model.default, cfg=cfg.model, app_cfg=cfg)


def _tui_theme(cfg) -> str:
    """Theme name from config (tui.theme), falling back to the default."""
    try:
        from .app.theme import DEFAULT_THEME
    except Exception:
        return ""
    try:
        name = str((getattr(cfg, "tui", {}) or {}).get("theme", "") or "")
        return name or DEFAULT_THEME
    except Exception:
        return DEFAULT_THEME


def _print_welcome(ws_path) -> None:
    """One-time welcome shown before the guided setup."""
    print("")
    print("╭──────────────────────────────────────────────╮")
    print("│  👋 欢迎使用 uiu — 你的个人 IP agent           │")
    print("│                                              │")
    print("│  第一次运行，先做两件事（约 1 分钟）：           │")
    print("│  ① 选一个模型（DeepSeek / OpenAI / 本地 Ollama）│")
    print("│  ② 填 API key（本地模型免 key）               │")
    print("│                                              │")
    print("│  之后就能进入全屏聊天界面开聊。                │")
    print("╰──────────────────────────────────────────────╯")
    print(f"  工作目录: {ws_path}")
    print("  （跳过向导: 启动时加 --skip-setup）")
    print("")
def _dispatch(args, parser: argparse.ArgumentParser) -> int:
    from .commands import (
        cmd_channel, cmd_config, cmd_cron, cmd_daemon, cmd_doctor, cmd_init, cmd_macro, cmd_model,
        cmd_sessions, cmd_show, cmd_update, cmd_version, cmd_skills, cmd_publish, cmd_plugins,
        cmd_serve, cmd_quick, cmd_backup, cmd_restore, cmd_audit, cmd_trash,
    )

    if args.version or args.cmd == "version":
        return cmd_version(args)

    handlers = {
        "init": cmd_init,
        "show": cmd_show,
        "model": cmd_model,
        "config": cmd_config,
        "skills": cmd_skills,
        "channel": cmd_channel,
        "update": cmd_update,
        "publish": cmd_publish,
        "plugins": cmd_plugins,
        "serve": cmd_serve,
        "cron": cmd_cron,
        "daemon": cmd_daemon,
        "sessions": cmd_sessions,
        "macro": cmd_macro,
        "quick": cmd_quick,
        "backup": cmd_backup,
        "restore": cmd_restore,
        "audit": cmd_audit,
        "trash": cmd_trash,
        "doctor": cmd_doctor,
    }
    handler = handlers.get(args.cmd)
    if handler is None:
        # default: TUI
        return _run_tui(args, parser)
    return handler(args)


def _resolve_workspace(args) -> Path | None:
    """Best-effort resolve workspace from args or env (before parser dispatch)."""
    ws_arg = getattr(args, "workspace", None) or os.environ.get("UIU_WORKSPACE")
    if ws_arg:
        return Path(ws_arg).expanduser()
    for p in (Path.cwd() / "workspace", Path.home() / "workspace", Path.home() / ".uiu" / "workspace"):
        if (p / "config.yaml").exists() or (p / "SOUL.md").exists():
            return p
    return None


def _normalize_workspace_flag(argv: list[str]) -> list[str]:
    """Move `--workspace X` (or `-w X`) before the subcommand.

    argparse defines --workspace at the top level only, so `uiu init --workspace X`
    would fail. Users naturally put it after the subcommand — accept both orders.
    """
    out: list[str] = []
    i = 0
    ws_flag: list[str] = []
    while i < len(argv):
        a = argv[i]
        if a in ("--workspace", "-w"):
            if i + 1 < len(argv):
                ws_flag = [a, argv[i + 1]]
                i += 2
                continue
            ws_flag = [a]
            i += 1
            continue
        out.append(a)
        i += 1
    return ws_flag + out


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # split argv: subcommands vs TUI default
    raw = list(argv) if argv is not None else list(sys.argv[1:])
    # Accept `--workspace` after the subcommand (hoist it to the front)
    if raw and raw[0] not in ("--workspace", "-w") and "--workspace" in raw:
        raw = _normalize_workspace_flag(raw)
    # If first arg starts with '-', treat as default (TUI) flags. Otherwise dispatch.
    if not raw or raw[0].startswith("-") and raw[0] not in ("-V", "--version"):
        # bare flags or nothing → TUI mode
        args = parser.parse_args([])
        # re-parse with the bare flags included (for things like --workspace)
        if raw:
            args = parser.parse_args(raw)
        # if cmd not set, force TUI by clearing cmd
        if args.cmd is None:
            args.cmd = "__tui__"
    else:
        args = parser.parse_args(raw)

    # Load .env: explicit workspace > cwd/workspace > home workspace > cwd
    ws_path = _resolve_workspace(args)
    env_paths = [
        Path.cwd() / ".env",
        Path.cwd() / "workspace" / ".env",
        Path.home() / ".uiu" / "workspace" / ".env",
    ]
    if ws_path:
        env_paths.insert(0, ws_path / ".env")
    _load_dotenv(paths=env_paths)

    if args.cmd == "__tui__":
        return _run_tui(args, parser)

    try:
        return _dispatch(args, parser)
    except RuntimeError as e:
        # 配置损坏等可预期错误：友好提示而非堆栈
        print(f"[error] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())