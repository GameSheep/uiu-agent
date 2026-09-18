"""文档与代码一致性（审计 §8.2 / §8.3）。

手写的数字会腐烂：README 曾长期写着「68 个内置工具」而注册表早已涨到 123。
这里把「生成物必须新鲜」「文档里的数字必须真实」「文档存在且被索引」变成可执行的检查。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def test_tools_doc_is_generated_and_fresh():
    """docs/tools.md 必须与工具注册表一致（用生成器的 --check 模式）。"""
    sys.path.insert(0, str(ROOT))
    from scripts.gen_tools_doc import main as gen_main

    assert gen_main(["--check"]) == 0, "docs/tools.md 已过期：python scripts/gen_tools_doc.py"


def test_tools_doc_covers_every_tool():
    from uiu import tools

    body = (DOCS / "tools.md").read_text(encoding="utf-8")
    missing = [name for name in tools.BUILTIN_TOOLS if ("`%s`" % name) not in body]
    assert not missing, "这些工具没出现在 docs/tools.md: %s" % (missing[:8])


def test_readme_tool_count_is_truthful():
    """README 里「总量」措辞必须等于注册表真实数量。

    只看两种总量声明：「N 个内置工具」与欢迎页那行的「⚙ N 工具」；
    分组计数（如「7 个系统工具」）是另一种声明，不归这条管。
    """
    from uiu import tools

    real = len(tools.BUILTIN_TOOLS)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    totals = {int(m.group(1)) for m in re.finditer("(\\d+)\\s*个内置工具", readme)}
    totals |= {int(m.group(1)) for m in re.finditer("⚙\\s*(\\d+)\\s*工具", readme)}
    assert totals, "README 里应当至少声明一次工具总数"
    assert totals == {real}, "README 写的是 %s，注册表实际是 %s" % (sorted(totals), real)


@pytest.mark.parametrize("name,needle", [
    ("architecture.md", "进程模型"),
    ("tools.md", "工具参考"),
    ("gateway-api.md", "鉴权矩阵"),
    ("troubleshooting.md", "故障排查"),
    ("release-checklist.md", "发版清单"),
    ("privacy.md", "隐私与数据处理"),
])
def test_docs_exist_and_are_substantial(name, needle):
    path = DOCS / name
    assert path.exists(), "缺少文档 %s" % name
    body = path.read_text(encoding="utf-8")
    assert needle in body, "%s 缺少关键小节：%s" % (name, needle)
    assert len(body.splitlines()) >= 20, "%s 太短，像是占位" % name


@pytest.mark.parametrize("name", [
    "architecture.md", "tools.md", "gateway-api.md", "troubleshooting.md", "tui-tour.md",
    "release-checklist.md", "product-readiness-2026-09-18.md", "privacy.md",
])
def test_readme_indexes_the_doc(name):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert ("docs/%s" % name) in readme, "README 没有索引 docs/%s" % name
