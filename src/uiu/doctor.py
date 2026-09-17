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
    # 网关鉴权：启用了 channel 就会起 webhook 端口。没有 token 时网关只绑本机
    # （安全默认），但用户通常是想对外接回调的 —— 提前说清楚，并支持 --fix 生成 token。
    enabled = [c for c in cfg.channels if getattr(c, "enabled", True)]
    if enabled and not (os.environ.get("UIU_GATEWAY_TOKEN", "")
                        or _env_file_value(root, "UIU_GATEWAY_TOKEN")):
        out.append(Finding(
            "channel/gateway-no-token", "warning",
            f"已启用 {len(enabled)} 个 channel 但未设置 UIU_GATEWAY_TOKEN："
            f"网关只会监听 127.0.0.1（要对外接回调必须先有 token）",
            fix_hint="uiu doctor --fix 会生成随机 token 写入 .env，"
                     "或 uiu config --set-secret UIU_GATEWAY_TOKEN=<随机串>",
            path="UIU_GATEWAY_TOKEN", can_fix=True))
    return out


# 可选能力栈：缺依赖时相关工具会在调用时报错，用户往往一头雾水。
# 这里统一体检并给出**可直接执行的安装命令**（info 级：不影响退出码）。
_OPTIONAL_STACKS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("browser", "browser", ("playwright", "browser_use"),
     "浏览器接管 / AI 浏览器"),
    ("desktop-uia", "desktop", ("uiautomation",),
     "UIA 控件定位（Windows 可访问性）"),
    ("voice-tts", "voice", ("edge_tts", "pyttsx3"),
     "语音播报（TTS）"),
    ("voice-stt", "voice", ("sounddevice", "speech_recognition"),
     "语音输入（STT）"),
    ("rag", "rag", ("chromadb", "sentence_transformers"),
     "本地向量记忆（RAG）"),
)


def _module_missing(name: str) -> bool:
    """单独抽出来是为了可测（测试里 monkeypatch 它，避免真的看环境）。"""
    import importlib.util as _ilu
    try:
        return _ilu.find_spec(name) is None
    except (ImportError, ValueError):
        return True


def _chk_optional_deps(root: Path) -> list[Finding]:
    """可选能力栈的依赖体检 + MCP 配置一致性。"""
    try:
        cfg = C.load_config(root)
    except Exception:
        return []

    out: list[Finding] = []
    for stack, extra, modules, label in _OPTIONAL_STACKS:
        if stack == "desktop-uia" and sys.platform != "win32":
            continue                    # 非 Windows 上装不了，platform/degraded 已经说过
        missing = [m for m in modules if _module_missing(m)]
        if missing:
            out.append(Finding(
                f"deps/{stack}-missing", "info",
                f"{label} 不可用：缺 {', '.join(missing)}",
                fix_hint=f"pip install 'uiu[{extra}]'（--fix 可直接装）",
                path=", ".join(missing), can_fix=True))

    if cfg.mcp_servers and _module_missing("mcp"):
        out.append(Finding("deps/mcp-missing", "warning",
                           "配置了 MCP 服务器但缺 mcp 包",
                           fix_hint="pip install 'uiu[mcp]'（--fix 可直接装）",
                           path="mcp", can_fix=True))

    if _module_missing("textual"):
        out.append(Finding("deps/textual-missing", "error",
                           "缺少 textual —— 全屏 TUI 无法启动（属于核心依赖，疑似安装不完整）",
                           fix_hint="pip install -e . 或 pip install 'uiu'", can_fix=False))
    return out


def _chk_platform(root: Path) -> list[Finding]:
    """非 Windows 上明确列出不可用能力（审计 §7.4）。"""
    import sys as _sys
    if _sys.platform == "win32":
        return []
    return [Finding(
        "platform/degraded", "warning",
        f"当前平台 {_sys.platform} 不是 Windows：桌面控制 / 屏幕 OCR / 微信闭环 / 输入法 / "
        f"宏录制回放 / 开机自启不可用（工具仍注册，调用时会提前返回）",
        fix_hint="这些能力建立在 Win32 API 上；完整能力请在 Windows 上运行。"
                 "矩阵见 docs/platform-support.md",
        can_fix=False)]


def _extra_for_dep_finding(finding_id: str) -> str | None:
    """把 deps/<stack>-missing 映射回 pip extra 名。"""
    for stack, extra, _modules, _label in _OPTIONAL_STACKS:
        if finding_id == f"deps/{stack}-missing":
            return extra
    if finding_id == "deps/mcp-missing":
        return "mcp"
    return None


def _run_pip(cmd: list[str]):
    """单独一层间接，方便测试替换（不去 monkeypatch 全局 subprocess）。"""
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def _pip_install_extra(extra: str) -> tuple[bool, str]:
    """--fix 的真动作：装对应的 extras（网络/索引不可用时会失败并如实报告）。"""
    cmd = [sys.executable, "-m", "pip", "install",
           "--disable-pip-version-check", f"uiu[{extra}]"]
    try:
        proc = _run_pip(cmd)
    except Exception as exc:                     # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode == 0:
        tail = " / ".join((proc.stdout or "").strip().splitlines()[-2:])
        return True, f"已安装 uiu[{extra}]" + (f"（{tail[:100]}）" if tail else "")
    err = " / ".join(((proc.stderr or proc.stdout or "").strip().splitlines()[-2:]))
    return False, (f"pip 安装失败 rc={proc.returncode}: {err[:160]}"
                   f"（可手动执行: {' '.join(cmd)}）")


def _env_file_value(root: Path, key: str) -> str:
    try:
        return C.parse_env_file(root / ".env").get(key, "")
    except Exception:
        return ""


# ---------- registry ----------

def _all_checks(root: Path) -> list[Finding]:
    out: list[Finding] = []
    for fn in (_chk_env, _chk_platform, _chk_workspace, _chk_config_yaml, _chk_model,
               _chk_env_file, _chk_channels, _chk_optional_deps):
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
        dep_extra = _extra_for_dep_finding(finding.id)
        if dep_extra:
            return _pip_install_extra(dep_extra)
        if finding.id == "channel/gateway-no-token":
            import secrets as _secrets
            env_path = root / ".env"
            existing = C.parse_env_file(env_path)
            existing["UIU_GATEWAY_TOKEN"] = _secrets.token_urlsafe(24)
            C.write_env_file(env_path, existing)
            return True, "已生成随机 UIU_GATEWAY_TOKEN 写入 .env（重启 serve 生效）"
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
               yes: bool = False, install_deps: bool = False, out=print) -> int:
    """Doctor entry. Returns exit code (0 clean, 1 findings, 2 runtime error).

    install_deps=False 时**绝不**执行 pip：可选栈动辄几十上百 MB（playwright 还要拖 chromium），
    不该被 `--fix --yes` 顺手装上。要装必须显式 `--install-deps`。
    """
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
    dep_findings = [f for f in items if f.can_fix and f.id.startswith("deps/")]
    fixable = [f for f in items if f.can_fix
               and (install_deps or not f.id.startswith("deps/"))]
    for f in dep_findings:
        if not install_deps:
            out(f"· 跳过 {f.id}（装可选依赖需显式 --install-deps）：{f.fix_hint}")
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
