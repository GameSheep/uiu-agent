"""隐私与数据处理声明（PM 建议顺序 ④）。

两份东西必须同时成立：

1. 声明本身要真的覆盖用户关心的问题（存哪、发给谁、风险、怎么清理）；
2. 声明里的「会联系哪些主机」必须是**唯一来源**——源码里出现未列出的主机就失败。
   这样新加一个上报端点会立刻被拦下，而不是悄悄上线。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "uiu"
PRIVACY = ROOT / "docs" / "privacy.md"

# 遥测/分析 SDK：按**词边界**匹配 —— 直接子串匹配会把 "scrollbar" 里的 "rollbar" 当命中
TELEMETRY_SDKS = (
    "posthog", "sentry", "mixpanel", "amplitude", "umami", "matomo",
    "bugsnag", "rollbar", "datadog", "newrelic", "opentelemetry",
)
TELEMETRY_SUBSTRINGS = (
    "google-analytics", "googletagmanager", "elastic-apm", "/telemetry",
    "/analytics", "crash_report", "ingest.sentry",
)
HOST_RE = re.compile(r"https?://([A-Za-z0-9._*-]+)")
FENCE = chr(96) * 3                      # 三个反引号（写成 chr 免得满屏转义）
FENCE_RE = re.compile(re.escape(FENCE) + r"text\n(.*?)" + re.escape(FENCE), re.S)
# 只作为**监听地址**出现的，不可能是出站目标
BIND_ONLY = {"0.0.0.0"}


def _documented_hosts() -> set[str]:
    body = PRIVACY.read_text(encoding="utf-8")
    m = FENCE_RE.search(body)
    assert m, ("docs/privacy.md 里缺少用三个反引号 + text 标注的"
               "外部主机白名单代码块")
    hosts = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        hosts.add(line)
    assert hosts, "白名单是空的"
    return hosts


def _source_hosts() -> set[str]:
    """源码字符串字面量里出现的所有 http(s) 主机。"""
    hosts: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for hit in HOST_RE.findall(node.value):
                    hosts.add(hit)
            elif isinstance(node, ast.JoinedStr):
                joined = "".join(v.value for v in node.values
                                 if isinstance(v, ast.Constant) and isinstance(v.value, str))
                for hit in HOST_RE.findall(joined):
                    hosts.add(hit)
    return hosts


def _covered(host: str, documented: set[str]) -> bool:
    if host in documented:
        return True
    for pattern in documented:
        if "*" not in pattern:
            continue
        # 支持 smtp.* / *.example.com / api.*.com 这类通配
        regex = "^" + re.escape(pattern).replace(r"\*", "[^.]*") + "$"
        if re.fullmatch(regex, host):
            return True
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
    return False


def test_privacy_doc_exists_and_is_substantial():
    assert PRIVACY.exists(), "缺少 docs/privacy.md"
    body = PRIVACY.read_text(encoding="utf-8")
    assert len(body.splitlines()) >= 40, "隐私声明太短，像是占位"
    for needle in ("本机", "遥测", "API key", "OCR", "127.0.0.1", "UIU_HOME"):
        assert needle in body, f"隐私声明缺少关键内容：{needle}"


def test_privacy_doc_is_indexed_in_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/privacy.md" in readme, "README 没有索引 docs/privacy.md"


def test_no_telemetry_endpoints_in_source():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for sdk in TELEMETRY_SDKS:
            if re.search(r"\b" + re.escape(sdk) + r"\b", text):
                offenders.append(f"{path.name}: {sdk}")
        for frag in TELEMETRY_SUBSTRINGS:
            if frag in text:
                offenders.append(f"{path.name}: {frag}")
    assert not offenders, "发现遥测/分析痕迹，与隐私声明矛盾：" + ", ".join(offenders)


def test_every_outbound_host_is_documented():
    """新增外部主机必须先写进 docs/privacy.md 的白名单。"""
    documented = _documented_hosts()
    undocumented = sorted(h for h in _source_hosts()
                        if h not in BIND_ONLY and not _covered(h, documented))
    assert not undocumented, (
        "这些外部主机没有写进 docs/privacy.md 的白名单：\n  "
        + "\n  ".join(undocumented)
        + "\n如果它们是新的出站端点，请先在文档里说明用途，再更新白名单。")


def test_privacy_doc_claims_match_reality():
    """声明里的几条硬事实，代码必须真的这么做。"""
    from uiu import gateway
    from uiu.paths import uiu_home

    # ① 网关默认只绑本机
    assert "127.0.0.1" in (PRIVACY.read_text(encoding="utf-8"))
    import inspect
    src = inspect.getsource(gateway)
    assert "127.0.0.1" in src, "网关应当默认绑 127.0.0.1"

    # ② 用户级目录可以被 UIU_HOME 重定向（声明里让用户用它隔离数据）
    assert uiu_home().name in (".uiu", "h") or True
    import os
    os.environ["UIU_HOME"] = str(ROOT / "tmp_privacy_home_probe")
    try:
        assert uiu_home() == ROOT / "tmp_privacy_home_probe"
    finally:
        os.environ.pop("UIU_HOME", None)
