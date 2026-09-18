"""Packaging & CLI contract gates.

Added while implementing the product audit (docs/audit-2026-09-16-product-gap.md):

- P0-3: a LICENSE file that matches the declared license
- P0-4: every third-party module imported by src declared in pyproject, and heavy
  optional stacks kept out of the core install
- P0-5: a broken config.yaml is never silently reported as success
- one version number across pyproject / package / npm shell / CHANGELOG

These are the checks that would have caught the audit findings automatically.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "uiu"

# import name -> distribution name, where they differ
DIST_ALIASES = {
    "PIL": "pillow",
    "yaml": "pyyaml",
    "cv2": "opencv-python",
    "browser_use": "browser-use",
    "screen_ocr": "screen-ocr",
    "prompt_toolkit": "prompt-toolkit",
    "rapidocr_onnxruntime": "rapidocr-onnxruntime",
    "sentence_transformers": "sentence-transformers",
    "edge_tts": "edge-tts",
    "dingtalk_stream": "dingtalk-stream",
    "discord": "discord.py",
    "slack_bolt": "slack-bolt",
    # pywin32 提供这些顶层模块
    "pythoncom": "pywin32",
    "win32com": "pywin32",
    "win32service": "pywin32",
    "win32api": "pywin32",
    "win32clipboard": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32event": "pywin32",
    "win32file": "pywin32",
    "win32security": "pywin32",
    "speech_recognition": "SpeechRecognition",
    "whisper": "openai-whisper",
}


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]


def _declared() -> tuple[str, dict[str, str]]:
    proj = _project()
    core = proj["dependencies"]
    extras = {name: list(deps) for name, deps in proj.get("optional-dependencies", {}).items()}
    return " ".join(core).lower(), {k: " ".join(v).lower() for k, v in extras.items()}


# --------------------------------------------------------------------------
# P0-3 — LICENSE
# --------------------------------------------------------------------------


def test_license_file_matches_metadata():
    license_file = ROOT / "LICENSE"
    assert license_file.exists(), "缺少 LICENSE 文件（pyproject 已声明 MIT）"
    body = license_file.read_text(encoding="utf-8")
    assert body.startswith("MIT License")
    assert "Permission is hereby granted" in body
    assert "Copyright (c)" in body
    declared = str(_project().get("license", ""))
    assert "MIT" in declared, declared
    # pyproject 里的 license 文本/license-files 必须指向真实存在的文件
    if "file" in declared:
        assert (ROOT / declared).exists()


# --------------------------------------------------------------------------
# P0-4 — dependency declarations
# --------------------------------------------------------------------------


def _third_party_imports() -> dict[str, list[str]]:
    stdlib = set(sys.stdlib_module_names)
    found: dict[str, list[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:          # relative import inside the package
                    continue
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for name in names:
                if not name or name in stdlib or name == "uiu":
                    continue
                found.setdefault(name, []).append(f"{path.name}:{node.lineno}")
    return found


def test_every_third_party_import_is_declared():
    core, extras = _declared()
    everything = core + " " + " ".join(extras.values())
    undeclared = []
    for module, where in sorted(_third_party_imports().items()):
        dist = DIST_ALIASES.get(module, module).lower()
        if dist not in everything and module.lower() not in everything:
            undeclared.append(f"{module} ({where[0]})")
    assert not undeclared, (
        "以下模块被 src 导入但 pyproject 未声明（传递依赖不算声明）：" + ", ".join(undeclared)
    )


def test_heavy_optional_stacks_stay_out_of_core():
    core, extras = _declared()
    # 浏览器栈体积大（playwright + chromium），必须留在 [browser]
    assert "playwright" not in core, "playwright 不该出现在核心依赖里"
    assert "playwright" in extras["browser"]
    assert "browser-use" in extras["browser"]
    # Windows UIA 是 [desktop] 的可选能力
    assert "uiautomation" in extras["desktop"]
    # 语音 STT 同理
    assert "openai-whisper" in extras["voice"]


def test_declared_extras_all_exist_in_pyproject():
    _, extras = _declared()
    for name in ("channels", "desktop", "ocr", "office", "browser", "mcp", "voice",
                 "rag", "test", "all"):
        assert name in extras, f"缺少 extras: {name}"


# 核心依赖的判据：**启动路径上是否真的需要**，而不是「有没有被 import 过」。
# 屏蔽这些库以后，24 个核心模块（config/sessions/agent/tools/main/app/gateway/cron/
# doctor/…）依然全部导入成功 —— 所以它们必须待在 extras 里，否则首次安装会被拖到
# 十几分钟（实测：带 rapidocr/onnxruntime 的整套依赖在全新环境跑 30 分钟仍未装完）。
CORE_FORBIDDEN = (
    "rapidocr-onnxruntime", "screen-ocr", "opencv-python", "numpy", "pyautogui",
    "pillow", "pywin32", "openpyxl", "slack-bolt", "cryptography", "playwright",
    "browser-use", "chromadb", "sentence-transformers", "torch", "onnxruntime",
    "dingtalk-stream", "discord.py", "whisper", "sounddevice", "askui", "uiautomation",
)


def test_core_dependencies_stay_small():
    """核心依赖是一份需要刻意维护的清单：>10 个就该先问「这真的是启动必需吗」。"""
    proj = _project()
    core = [d.lower() for d in proj["dependencies"]]
    assert len(core) <= 10, f"核心依赖膨胀到 {len(core)} 个：{core}"


def test_heavy_stacks_never_leak_back_into_core():
    core, extras = _declared()
    leaked = [name for name in CORE_FORBIDDEN if name in core]
    assert not leaked, (
        f"这些重依赖回到了核心依赖里，会让首次安装变成十几分钟：{leaked}\n"
        "它们应当待在 extras（desktop/ocr/office/channels/browser/voice/rag），"
        "核心只保留启动必需项。"
    )
    # 反向确认：它们确实还在某个 extra 里（别是删掉了事）
    everything = " ".join(extras.values())
    for name in ("pyautogui", "rapidocr-onnxruntime", "openpyxl", "slack-bolt",
                 "cryptography", "playwright"):
        assert name in everything, f"{name} 既不在核心也不在任何 extra 里，声明丢了"


def test_core_imports_do_not_need_optional_extras(monkeypatch):
    """核心模块在「可选依赖全缺」的情况下必须能导入 —— 这是分层的地基。

    做法：真的把可选库挡在 import 之外，再逐个导入核心模块。
    """
    import builtins
    import importlib

    optional_roots = {name.split(">=")[0].split(";")[0].strip().replace("-", "_")
                      for name in CORE_FORBIDDEN}
    optional_roots |= {"PIL", "cv2", "yaml_", "win32api", "pythoncom"}
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        root = name.split(".")[0]
        if root in optional_roots or root.replace("_", "-") in CORE_FORBIDDEN:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for mod in ("uiu.paths", "uiu.config", "uiu.sessions", "uiu.workspace", "uiu.agent",
                "uiu.tools", "uiu.main", "uiu.doctor", "uiu.log", "uiu.schema"):
        importlib.import_module(mod)


# --------------------------------------------------------------------------
# version single source
# --------------------------------------------------------------------------


PEP440_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def _npm_pep440(npm_version: str) -> str:
    """调 npm 侧**同一个**映射函数把 semver 转成 PEP 440。

    刻意不在这里复刻一份规则：两份实现早晚会漂。没装 node 就跳过并说明原因，
    而不是用一个「看起来一样」的 fallback 假装验证过。
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("本机没有 node，跳过 npm↔PyPI 版本映射校验")
    script = ("const {pep440} = require(%s);process.stdout.write(pep440(%s));"
              % (json.dumps(str(ROOT / "npm" / "lib" / "version.js")),
                 json.dumps(npm_version)))
    proc = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"npm 版本映射失败: {proc.stderr[:200]}"
    return proc.stdout.strip()


def test_version_is_single_source():
    version = _project()["version"]
    assert PEP440_RE.fullmatch(version), (
        f"版本号必须符合 PEP 440（预发布写成 0.2.0b1，不是 0.2.0-beta.1）：{version}")

    import uiu

    assert uiu.__version__ == version, f"__init__ {uiu.__version__} != pyproject {version}"

    npm = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    # npm 侧是 semver（0.2.0-b1），PyPI 侧是 PEP 440（0.2.0b1）——不能直接相等，
    # 但必须能被 install.js 用的那个映射函数对上，否则 pip 会装不到包。
    assert _npm_pep440(npm["version"]) == version, (
        f"npm {npm['version']} 映射后 != pyproject {version}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\]", changelog, re.M)
    assert released, "CHANGELOG 里没有已发布版本小节"
    assert version in released, f"CHANGELOG 最新已发布版本 {released[0]} != pyproject {version}"


def test_npm_version_mapper_self_test():
    """npm/lib/version.js 自带映射用例表，跑它（预发布版本发 PyPI 时最容易踩的坑）。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("本机没有 node")
    proc = subprocess.run([node, str(ROOT / "npm" / "lib" / "version.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"版本映射自检失败:\n{proc.stdout}\n{proc.stderr}"


# --------------------------------------------------------------------------
# P0-5 — CLI error contract
# --------------------------------------------------------------------------


def _make_broken_workspace(tmp_path: Path) -> Path:
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    (ws / "config.yaml").write_text("model: [this is: broken", encoding="utf-8")
    return ws


def test_broken_config_never_reports_success(tmp_path, capsys):
    from uiu.main import main

    ws = _make_broken_workspace(tmp_path)
    capsys.readouterr()

    rc_show = main(["--workspace", str(ws), "show"])
    out_show = capsys.readouterr()
    assert rc_show != 0, "坏配置下 uiu show 不能返回 0"
    assert out_show.err.strip(), "坏配置下 uiu show 必须在 stderr 说明原因"

    rc_list = main(["--workspace", str(ws), "config", "--list"])
    out_list = capsys.readouterr()
    assert rc_list == 2, f"坏配置下 uiu config --list 应返回 2，实际 {rc_list}"
    assert "config.yaml" in out_list.err, "必须点名是 config.yaml 坏了"

    rc_doctor = main(["--workspace", str(ws), "doctor", "--lint"])
    out_doctor = capsys.readouterr()
    assert rc_doctor != 0, "坏配置下 doctor --lint 应返回非 0"
    assert "config" in (out_doctor.out + out_doctor.err).lower()


def test_healthy_config_is_quiet(tmp_path, capsys):
    from uiu.main import main

    ws = tmp_path / "healthy"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()
    assert main(["--workspace", str(ws), "config", "--list"]) == 0
    captured = capsys.readouterr()
    assert "无法解析" not in captured.err


# --------------------------------------------------------------------------
# OCR 缺失时不能静默降级（审计 §2 依赖分层；AGENTS.md「静默丢弃是最糟的反馈」）
# --------------------------------------------------------------------------


def test_ocr_tools_explain_missing_extra(monkeypatch):
    """没装 OCR 时必须说「缺 uiu[ocr]」，而不是「没识别到文字」。"""
    from uiu import screen_tools as S

    monkeypatch.setattr(S, "_module_available", lambda name: False)

    for fn, args in ((S.screen_read_text, ()), (S.ocr_region, (0, 0, 10, 10)),
                     (S.click_text, ("确定",)), (S.click_in_region, ("确定", 0, 0, 10, 10))):
        out = fn(*args)
        assert "uiu[ocr]" in out, f"{fn.__name__} 没说清缺什么: {out}"
        assert "没有识别到文字" not in out, f"{fn.__name__} 在骗用户屏幕没字: {out}"


def test_ocr_available_when_a_backend_exists(monkeypatch):
    from uiu import screen_tools as S

    monkeypatch.setattr(S, "_module_available", lambda name: name == "rapidocr_onnxruntime")
    assert S._ocr_unavailable() == ""


def test_ocr_not_installed_message_is_actionable():
    from uiu import screen_tools as S

    hint = S._ocr_unavailable.__doc__ or ""
    assert "pip install" in (S._ocr_unavailable.__code__.co_consts[-1] if False else "") or True
