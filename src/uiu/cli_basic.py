"""基础命令：init / show / version / audit / backup / restore / trash（自原 commands.py 按域拆分；审计 §2.1）。"""

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

from .cli_model import (
    _setup_playwright_browsers_async,
)

from .cli_shared import (
    _confirm,
    _print_err,
    _print_ok,
    _workspace,
)


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


def cmd_version(args) -> int:
    from . import __version__
    print(f"uiu {__version__}")
    return 0


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
