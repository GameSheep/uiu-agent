"""Doctor — diagnose & fix uiu configuration problems (OpenClaw doctor, minimal).

Design (mirrors OpenClaw doctor, trimmed to uiu's failure surface):
- registry of checks: each is detect(workspace) -> list[Finding] | [] and
  optional repair(workspace, finding) -> bool. detect NEVER raises; a broken
  config must not stop the doctor.
- Finding: {id, severity(info|warning|error), message, fix_hint, path?}
- CLI:
    uiu doctor             # guided: list findings, offer fixes per item
    uiu doctor --lint      # read-only, structured report, no fixes
    uiu doctor --fix --yes # non-interactive: apply all auto-fixes
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config as C


@dataclass
class Finding:
    id: str
    severity: str            # info | warning | error
    message: str
    fix_hint: str = ""
    path: str = ""
    can_fix: bool = False


# ---------- individual checks (all pure detect; never raise) ----------

def _chk_env() -> list[Finding]:
    """Python version & platform sanity."""
    out = []
    if sys.version_info < (3, 10):
        out.append(Finding("env/python-version", "error",
                           f"Python {sys.version.split()[0]} 过旧（需要 ≥3.10）",
                           fix_hint="安装 Python 3.10+", can_fix=False))
    try:
        import yaml  # noqa: F401
    except ImportError:
        out.append(Finding("env/pyyaml", "error", "缺少依赖 PyYAML（config 读写需要）",
                           fix_hint="pip install pyyaml", can_fix=False))
    return out


def _chk_workspace(root: Path) -> list[Finding]:
    """Workspace dir + persona files exist (non-fatal but warned)."""
    out = []
    if not root.exists():
        out.append(Finding("workspace/missing", "error", f"workspace 不存在: {root}",
                           fix_hint="运行 uiu init 创建", path=str(root), can_fix=True))
        return out
    from .workspace import PERSONA_FILES
    missing = [f for f in PERSONA_FILES if not (root / f).exists()]
    if missing:
        out.append(Finding("workspace/persona-files", "warning",
                           f"缺少人设文件: {', '.join(missing)}",
                           fix_hint="uiu init 会补全", path=str(root), can_fix=True))
    return out


def _chk_config_yaml(root: Path) -> list[Finding]:
    """config.yaml parseable & structurally valid."""
    p = C.config_yaml_path(root)
    if not p.exists():
        return [Finding("config/missing", "error", "缺少 config.yaml",
                        fix_hint="uiu init 会生成默认配置", path=str(p), can_fix=True)]
    try:
        C.load_config(root)
    except Exception as e:
        # 尝试备份坏文件并给提示（repair 会做）
        return [Finding("config/parse-error", "error", f"config.yaml 解析失败: {e}",
                        fix_hint="备份后重置为默认配置（会丢自定义项）", path=str(p), can_fix=True)]
    return []


def _chk_model(root: Path) -> list[Finding]:
    """Model config: provider known, api_mode valid, api_key_env set."""
    out = []
    try:
        cfg = C.load_config(root)
    except Exception:
        return out  # config 已坏由 _chk_config_yaml 报
    m = cfg.model
    try:
        from .providers import find_profile
        prof = find_profile(m.provider)
    except Exception:
        prof = None
    if prof is None and m.provider != "custom":
        out.append(Finding("model/unknown-provider", "warning",
                           f"provider '{m.provider}' 不在注册表（可能拼错或插件未装）",
                           fix_hint="uiu model 重新选一个", can_fix=False))
    if m.api_mode not in C.API_MODES:
        out.append(Finding("model/bad-api-mode", "error",
                           f"api_mode '{m.api_mode}' 非法（支持: {', '.join(C.API_MODES)}）",
                           fix_hint="改为 chat_completions 或 anthropic_messages",
                           path="model.api_mode", can_fix=True))
    if m.api_mode == "bedrock_converse":
        out.append(Finding("model/bedrock-unsupported", "warning",
                           "bedrock_converse 尚未实现，会回退 openai 协议",
                           fix_hint="改 chat_completions", path="model.api_mode", can_fix=True))
    key_name = m.api_key_env
    if not key_name:
        try:
            key_name = prof.api_key_env if prof else ""
        except Exception:
            key_name = ""
    if not key_name:
        key_name = "OPENAI_API_KEY"
    key = os.environ.get(key_name, "") or _env_file_value(root, key_name)
    if not key and (prof is None or getattr(prof, "auth_type", "api_key") != "none"):
        out.append(Finding("model/no-api-key", "error",
                           f"未设置 API key（{key_name}）",
                           fix_hint=f"uiu config --set-secret {key_name}=sk-xxx",
                           path=key_name, can_fix=False))
    # TUI 主题：写错名字会让启动回退默认值，这里提前报出来
    try:
        from .app.theme import COLOR_FIELDS, DEFAULT_THEME, THEMES
        tui = getattr(cfg, "tui", {}) or {}
        theme = str(tui.get("theme", "") or "")
        if theme and theme not in THEMES:
            out.append(Finding("tui/unknown-theme", "warning",
                               f"tui.theme '{theme}' 不是内置主题（会回退 {DEFAULT_THEME}）",
                               fix_hint=f"可选：{', '.join(THEMES)}（--fix 会重置为 {DEFAULT_THEME}）",
                               path="tui.theme", can_fix=True))
        colors = tui.get("colors") or {}
        if isinstance(colors, dict) and colors:
            unknown = [k for k in colors if k not in COLOR_FIELDS]
            if unknown:
                out.append(Finding("tui/unknown-color-slot", "warning",
                                   f"tui.colors 里有未知色位：{', '.join(unknown)}（会被忽略）",
                                   fix_hint=f"可选：{', '.join(COLOR_FIELDS)}（--fix 会删掉未知色位）",
                                   path="tui.colors", can_fix=True))
            for slot, value in colors.items():
                if slot not in COLOR_FIELDS:
                    continue
                try:
                    from textual.color import Color
                    Color.parse(str(value))
                except Exception:
                    out.append(Finding("tui/bad-color", "warning",
                                       f"tui.colors.{slot} 颜色非法：{value}",
                                       fix_hint="用 #RRGGBB 或颜色名（uiu config --color "
                                                f"{slot}=#4C9AFF；--fix 会移除该色位）",
                                       path=f"tui.colors.{slot}", can_fix=True))
    except Exception:
        pass
    return out


def _chk_env_file(root: Path) -> list[Finding]:
    """.env missing or has obviously broken lines (silent-drop risk)."""
    p = root / ".env"
    if not p.exists():
        # 仅当 model 确实需要 key 才提示（ollama/vllm 等本地 provider 无需）
        needs_key = True
        try:
            cfg = C.load_config(root)
            from .providers import find_profile
            prof = find_profile(cfg.model.provider)
            needs_key = prof is None or getattr(prof, "auth_type", "api_key") != "none"
        except Exception:
            pass
        if needs_key:
            return [Finding("env/dotenv-missing", "warning",
                            "workspace/.env 不存在（API key 无处存放）",
                            fix_hint="uiu init 会创建模板", path=str(p), can_fix=True)]
        return []
    bad = []
    for i, raw in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" in line:
            continue
        bad.append(f"第{i}行: {line[:40]}")
    if bad:
        return [Finding("env/dotenv-bad-lines", "warning",
                        "".join(f"  {b}\n" for b in bad) + ".env 有无法解析的行（会被静默忽略）",
                        fix_hint="手动检查这些行", path=str(p), can_fix=False)]
    return []


def _chk_channels(root: Path) -> list[Finding]:
    """Enabled channels: token env name resolvable."""
    try:
        cfg = C.load_config(root)
    except Exception:
        return []
    out = []
    for c in cfg.channels:
        if not getattr(c, "enabled", True):
            continue
        tok = os.environ.get(c.secret_env or "", "") or _env_file_value(root, c.secret_env or "")
        if not tok and c.secret_env:
            out.append(Finding(f"channel/{c.name}-token", "warning",
                               f"channel '{c.name}' 未设置 token（{c.secret_env}）",
                               fix_hint=f"uiu config --set-secret {c.secret_env}=...",
                               path=c.secret_env, can_fix=False))
    return out


def _chk_optional_deps(root: Path) -> list[Finding]:
    """Optional extras present in config but dependency missing."""
    try:
        cfg = C.load_config(root)
    except Exception:
        return []
    out = []
    if cfg.mcp_servers:
        try:
            import mcp  # noqa: F401
        except ImportError:
            out.append(Finding("deps/mcp-missing", "warning",
                               "配置了 MCP 服务器但缺 mcp 包",
                               fix_hint="pip install 'uiu[mcp]'", can_fix=False))
    return out


def _env_file_value(root: Path, key: str) -> str:
    try:
        return C.parse_env_file(root / ".env").get(key, "")
    except Exception:
        return ""


# ---------- registry ----------

def _all_checks(root: Path) -> list[Finding]:
    out: list[Finding] = []
    for fn in (_chk_env, _chk_workspace, _chk_config_yaml, _chk_model, _chk_env_file,
               _chk_channels, _chk_optional_deps):
        try:
            out.extend(fn(root) or [])
        except Exception:
            continue  # 单个检查崩溃不拖垮 doctor
    return out


def _fix_one(root: Path, finding: Finding) -> tuple[bool, str]:
    """Apply a single fix. Returns (ok, message)."""
    try:
        if finding.id == "workspace/missing" or finding.id == "workspace/persona-files":
            C.ensure_workspace(root)
            return True, "已调用 uiu init 补全 workspace 文件"
        if finding.id == "config/missing":
            C.save_config(root, C.AppConfig())
            return True, "已生成默认 config.yaml"
        if finding.id == "config/parse-error":
            p = C.config_yaml_path(root)
            bak = p.with_suffix(".yaml.bak")
            shutil.copy2(p, bak)
            C.save_config(root, C.AppConfig())
            return True, f"坏 config.yaml 已备份为 {bak.name} 并重置为默认"
        if finding.id == "model/bad-api-mode":
            cfg = C.load_config(root)
            cfg.model.api_mode = "chat_completions"
            C.save_config(root, cfg)
            return True, "api_mode 已重置为 chat_completions"
        if finding.id == "model/bedrock-unsupported":
            cfg = C.load_config(root)
            cfg.model.api_mode = "chat_completions"
            C.save_config(root, cfg)
            return True, "bedrock_converse → chat_completions"
        if finding.id == "env/dotenv-missing":
            C.ensure_workspace(root)
            return True, "已创建 .env 模板"
        if finding.id == "tui/unknown-theme":
            from .app.theme import DEFAULT_THEME
            cfg = C.load_config(root)
            prefs = dict(getattr(cfg, "tui", {}) or {})
            prefs["theme"] = DEFAULT_THEME
            cfg.tui = prefs
            C.save_config(root, cfg)
            return True, f"tui.theme 已重置为 {DEFAULT_THEME}"
        if finding.id in ("tui/bad-color", "tui/unknown-color-slot"):
            from .app.theme import COLOR_FIELDS
            cfg = C.load_config(root)
            prefs = dict(getattr(cfg, "tui", {}) or {})
            colors = dict(prefs.get("colors") or {})
            if finding.id == "tui/bad-color":
                slot = (finding.path or "").rsplit(".", 1)[-1]
                colors.pop(slot, None)
                note = f"已移除非法色位 {slot}"
            else:
                dropped = [k for k in colors if k not in COLOR_FIELDS]
                for k in dropped:
                    colors.pop(k, None)
                note = f"已移除未知色位：{', '.join(dropped) or '(无)'}"
            prefs["colors"] = colors
            cfg.tui = prefs
            C.save_config(root, cfg)
            return True, note
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    return False, "该项无自动修复（见 fix_hint 手动处理）"


# ---------- output ----------

def _render(items: list[Finding]) -> str:
    if not items:
        return "[ok] 未发现问题"
    lines = []
    for f in items:
        lines.append(f"[{f.severity}] {f.id}: {f.message}")
        if f.path:
            lines.append(f"    path: {f.path}")
        if f.fix_hint:
            lines.append(f"    fix: {f.fix_hint}")
    return "\n".join(lines)


# ---------- CLI entry ----------

def run_doctor(workspace: Path, lint: bool = False, fix: bool = False,
               yes: bool = False, out=print) -> int:
    """Doctor entry. Returns exit code (0 clean, 1 findings, 2 runtime error)."""
    items = _all_checks(workspace)
    errs = [f for f in items if f.severity == "error"]
    warns = [f for f in items if f.severity == "warning"]

    if lint:
        out(_render(items))
        return 1 if errs else 0

    out(f"uiu doctor · workspace: {workspace} · python {sys.version.split()[0]}")
    if not items:
        out("[ok] 一切正常")
        return 0
    out(_render(items))
    if not fix:
        out("")
        out("提示: 加 --fix 自动修复可修项（逐项确认），--fix --yes 全部自动修")
        return 1 if errs or warns else 0

    # fix mode: 逐项确认（除非 --yes）
    fixable = [f for f in items if f.can_fix]
    if not fixable:
        out("(没有可自动修复的项)")
        return 1 if errs else 0
    for f in fixable:
        if not yes:
            try:
                ans = input(f"修复 [{f.id}]? {f.fix_hint or f.message} [y/N] ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("y", "yes"):
                out(f"· 跳过 {f.id}")
                continue
        ok, msg = _fix_one(workspace, f)
        if ok:
            out(f"[ok] 已修复 {f.id}: {msg}")
        else:
            out(f"[x] 修复失败 {f.id}: {msg}")
    # 重扫确认
    remaining = _all_checks(workspace)
    if remaining:
        out("")
        out("修复后仍存在问题:")
        out(_render(remaining))
    return 1 if remaining else 0
