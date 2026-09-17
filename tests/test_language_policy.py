"""语言策略（审计 §1.5 / P2-14）。

决策：**产品只支持简体中文**，不做完整 i18n 层（1,800+ 行文案、无 gettext，引入翻译层的
成本远大于当前用户收益）。但「只支持中文」不等于「随便混英文」——所以：

1. 面向用户的反馈（`_print_ok` / `_print_err` / `fail` / `result(human=...)`）必须是中文；
2. 机器可读的部分（`--json` 信封的键）保持英文且稳定，不受文案改动影响；
3. README 必须写明语言边界，别让用户装完才发现。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "uiu"
CJK = re.compile("[\u4e00-\u9fff]")
FEEDBACK_FUNCS = {"_print_ok", "_print_err", "fail"}
# 语言中立的例外（命令示例/字段名这类不该翻译的东西）
ALLOWLIST: set[str] = set()


def _messages() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            texts: list[str] = []
            if name in FEEDBACK_FUNCS and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    texts.append(first.value)
                elif isinstance(first, ast.JoinedStr):
                    texts.append("".join(v.value for v in first.values
                                         if isinstance(v, ast.Constant)))
            for kw in getattr(node, "keywords", []):
                if kw.arg == "human" and isinstance(kw.value, ast.Constant):
                    texts.append(kw.value.value or "")
            for text in texts:
                if text and text.strip():
                    out.append((str(path.relative_to(SRC)), node.lineno, text.strip()))
    return out


def test_user_facing_feedback_is_chinese():
    offenders = [(p, ln, t) for p, ln, t in _messages()
                 if not CJK.search(t) and len(t) >= 8 and t not in ALLOWLIST]
    assert not offenders, (
        "面向用户的反馈必须是中文（或加入 ALLOWLIST 并说明理由）：\n"
        + "\n".join(f"  {p}:{ln}: {t}" for p, ln, t in offenders[:12]))


def test_language_decision_is_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "简体中文" in readme, "README 必须写明当前的语言支持范围"


def test_json_envelope_keys_are_language_neutral():
    """机器可读的键固定为英文；文案改动不能影响它们。"""
    from uiu import cli_io

    full = cli_io._envelope("sessions.usage", True, {"count": 1}, "")
    assert set(full) == {"ok", "command", "data"}
    minimal = cli_io._envelope("x", False, None, "出错了")
    assert set(minimal) == {"ok", "command", "error"}
    assert all(k.isascii() for k in full)


def test_feedback_functions_still_used(tmp_path):
    """哨兵：如果这些函数被改名/移除，上面的扫描会静默失效。"""
    from uiu import commands

    assert hasattr(commands, "_print_ok") and hasattr(commands, "_print_err")
    assert _messages(), "扫描不到任何用户可见文案，检查扫描逻辑是否失效"
