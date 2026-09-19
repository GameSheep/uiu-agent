"""渠道：channel add/list/enable/remove/test（自原 commands.py 按域拆分；审计 §2.1）。"""

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
    _print_err,
    _print_ok,
    _workspace,
)


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
            print("     注意：webhook 只接收、不回消息；回复会存进会话 gw-<chat_id>"
                  "（uiu sessions show gw-<id>）")
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
        _print_ok(f"{args.name} 已{'启用' if args.action == 'enable' else '停用'}")
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
