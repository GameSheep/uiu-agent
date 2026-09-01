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


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader — sets only keys not already in environ."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
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

    # skills
    psk = sub.add_parser("skills", help="manage skills")
    psk_sub = psk.add_subparsers(dest="action", metavar="<action>", required=True)
    psk_sub.add_parser("list", help="list installed skills")
    psk_ask = psk_sub.add_parser("add", help="create a new skill from template")
    psk_ask.add_argument("name", help="skill name (will be the directory name)")
    psk_edit = psk_sub.add_parser("edit", help="open SKILL.md in $EDITOR")
    psk_edit.add_argument("name")
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

    # publish
    pp = sub.add_parser("publish", help="build & upload to PyPI")
    pp.add_argument("--test", action="store_true", help="publish to TestPyPI (dry run for real PyPI)")
    pp.add_argument("--token", help="PyPI API token (or set env PYPI_TOKEN)")

    return p


def _run_tui(args, parser: argparse.ArgumentParser) -> int:
    from .config import AppConfig, ModelConfig, load_config
    from .llm import make_client
    from .tui import repl
    from .workspace import load_workspace

    from .commands import _workspace as _ws, cmd_init, cmd_model

    ws_path = _ws(args)

    # First-run UX: workspace missing -> auto init + run model wizard
    if not (ws_path / "SOUL.md").exists():
        print(f"[first-run] workspace 不存在，正在初始化: {ws_path}")
        # reuse cmd_init with a namespace that has no extra attrs
        import argparse as _argparse
        init_ns = _argparse.Namespace(workspace=str(ws_path) if args.workspace else None)
        cmd_init(init_ns)

    cfg = load_config(ws_path)

    # First-run UX: no API key -> auto run model wizard
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

    if needs_key:
        print("\n[first-run] 还没有配置模型，先配一个（也可以随时用 `uiu model` 切换）")
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
    return repl(client, ws, model=cfg.model.default, cfg=cfg.model)


def _dispatch(args, parser: argparse.ArgumentParser) -> int:
    from .commands import (
        cmd_channel, cmd_config, cmd_init, cmd_model, cmd_show,
        cmd_update, cmd_version, cmd_skills, cmd_publish, cmd_plugins,
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
    }
    handler = handlers.get(args.cmd)
    if handler is None:
        # default: TUI
        return _run_tui(args, parser)
    return handler(args)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    # split argv: subcommands vs TUI default
    raw = argv if argv is not None else sys.argv[1:]
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

    _load_dotenv()

    if args.cmd == "__tui__":
        return _run_tui(args, parser)

    return _dispatch(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())