"""CI 配置契约：流水线装的 extras 必须覆盖测试真正用到的可选依赖。

为什么需要它：把重依赖从核心拆到 extras 之后（审计 §2 / PM 建议顺序 ②），
CI 里那句 `pip install -e ".[test,browser]"` 就**不再够用**了——
测试会 import `PIL`/`cv2`/`numpy`/`pyautogui`/`win32gui`（desktop）和 `cryptography`（channels），
核心不再提供它们 → 流水线在 import 阶段就红。
这个坑真发生过（分层那次提交），所以固定成断言。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI = ROOT / ".github" / "workflows" / "ci.yml"
TESTS = ROOT / "tests"

# 测试会碰到的「非核心」模块 → 提供它的 extra（名字按 pyproject 的 extras 写）
_MODULE_EXTRA = {
    "PIL": "desktop", "cv2": "desktop", "numpy": "desktop", "pyautogui": "desktop",
    "win32api": "desktop", "win32con": "desktop", "win32gui": "desktop",
    "win32clipboard": "desktop", "win32com": "desktop", "pythoncom": "desktop",
    "uiautomation": "desktop", "askui": "desktop",
    "openpyxl": "office",
    "rapidocr_onnxruntime": "ocr", "screen_ocr": "ocr",
    "slack_bolt": "channels", "cryptography": "channels",
    "dingtalk_stream": "channels", "discord": "channels",
    "playwright": "browser", "browser_use": "browser",
    "edge_tts": "voice", "pyttsx3": "voice", "sounddevice": "voice",
    "speech_recognition": "voice", "whisper": "voice", "scipy": "voice",
    "chromadb": "rag", "sentence_transformers": "rag", "mcp": "mcp",
}


def _declared_extras() -> dict[str, list[str]]:
    import tomllib

    proj = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {k: list(v) for k, v in proj["project"].get("optional-dependencies", {}).items()}


def _expand(extras: set[str]) -> set[str]:
    """把 [all] 这类「只引用别的 extras」的名字展开成实际集合（读 pyproject，不写死）。"""
    declared = _declared_extras()
    out = set(extras)
    changed = True
    while changed:
        changed = False
        for name in list(out):
            for dep in declared.get(name, []):
                m = re.fullmatch(r"uiu\[([^\]]+)\]", dep.strip())
                if m:
                    for sub in m.group(1).split(","):
                        sub = sub.strip()
                        if sub and sub not in out:
                            out.add(sub)
                            changed = True
    return out


def _ci_extras() -> set[str]:
    body = CI.read_text(encoding="utf-8")
    extras: set[str] = set()
    for m in re.finditer(r'pip install -e "\.\[([^\]]+)\]"', body):
        extras |= {e.strip() for e in m.group(1).split(",") if e.strip()}
    assert extras, "在 ci.yml 里找不到 pip install -e \".[...]\" 的安装行"
    return _expand(extras)


def _test_imports() -> set[str]:
    roots: set[str] = set()
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                roots.add(node.module.split(".")[0])
    return roots


def test_ci_installs_every_extra_the_tests_need():
    imported = _test_imports()
    needed = {extra for mod, extra in _MODULE_EXTRA.items() if mod in imported}
    have = _ci_extras()
    missing = sorted(needed - have)
    assert not missing, (
        f"CI 没装这些 extras，但测试会 import 对应模块 → 流水线必红：{missing}\n"
        f"（当前 CI 装的是：{sorted(have)}）")


def test_ci_installs_the_test_extra_and_local_package():
    body = CI.read_text(encoding="utf-8")
    assert "-e " in body, "CI 必须安装本地包（-e），否则测的不是这份代码"
    assert "test" in _ci_extras(), "CI 没装 [test]（跑不了 pytest/coverage）"


def test_ci_runs_the_gates_we_document():
    """README/AGENTS 里承诺的门禁，CI 里必须真的跑。"""
    body = CI.read_text(encoding="utf-8")
    for needle in ("pytest tests", "cov-fail-under", "cli_smoke.py", "compileall"):
        assert needle in body, f"CI 缺少门禁：{needle}"
