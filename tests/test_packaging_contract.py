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
    for name in ("channels", "desktop", "browser", "mcp", "voice", "rag", "test", "all"):
        assert name in extras, f"缺少 extras: {name}"


# --------------------------------------------------------------------------
# version single source
# --------------------------------------------------------------------------


def test_version_is_single_source():
    version = _project()["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    import uiu

    assert uiu.__version__ == version, f"__init__ {uiu.__version__} != pyproject {version}"

    npm = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    assert npm["version"] == version, f"npm {npm['version']} != pyproject {version}"

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    released = re.findall(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\]", changelog, re.M)
    assert released, "CHANGELOG 里没有已发布版本小节"
    assert version in released, f"CHANGELOG 最新已发布版本 {released[0]} != pyproject {version}"


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
