#!/usr/bin/env python
"""Generate docs/tools.md from the live tool registry.

为什么生成而不是手写：README 里写死的「68 个工具」在注册表涨到 123 个之后就成了假话
（审计 §8.3）。这里以 registry 为唯一事实来源，CI/测试用 --check 校验文档是否过期。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

HEADER = """# 工具参考

> 本文件由 `python scripts/gen_tools_doc.py` 从 `uiu.tools` 注册表生成，**请勿手改**。
> 重新生成：`python scripts/gen_tools_doc.py`；CI 用 `--check` 校验是否过期。

共 **{count}** 个内置工具，按定义模块分组。带 ⚠ 标记的工具**默认需要用户确认**；
此外 `shell_exec` 与文件读写会在调用时按语义/路径动态判定（见 audit §5.2/§5.3）。
"""


def _always_confirm() -> set[str]:
    names: set[str] = set()
    try:
        from uiu.confirm import CONFIRM_TOOLS
        names |= set(CONFIRM_TOOLS)
    except Exception:
        pass
    try:
        from uiu.risk_guardrails import DEFAULT_CONFIRM_TOOLS
        names |= set(DEFAULT_CONFIRM_TOOLS)
    except Exception:
        pass
    return names


def _group_of(name: str, fn) -> str:
    module = (getattr(fn, "__module__", "") or "").replace("uiu.", "")
    if module and module != "tools":
        return module
    return name.split("_")[0] or "misc"


def _params(schema: dict) -> str:
    params = (schema.get("function", {}).get("parameters") or {})
    props = params.get("properties") or {}
    required = set(params.get("required") or [])
    if not props:
        return "无参数"
    parts = []
    for pname, spec in props.items():
        kind = spec.get("type") or "any"
        mark = "*" if pname in required else ""
        parts.append(f"`{pname}` {kind}{mark}")
    return "、".join(parts)


def render() -> str:
    from uiu import tools as T

    defs = T.tool_defs()
    confirm = _always_confirm()
    groups: dict[str, list[dict]] = {}
    for schema in defs:
        fn_meta = schema["function"]
        name = fn_meta["name"]
        entry = T.BUILTIN_TOOLS.get(name) or {}
        groups.setdefault(_group_of(name, entry.get("fn")), []).append(schema)

    out = [HEADER.format(count=len(defs))]
    for group in sorted(groups):
        items = sorted(groups[group], key=lambda s: s["function"]["name"])
        out.append(f"## {group} ({len(items)})\n")
        for schema in items:
            meta = schema["function"]
            name = meta["name"]
            flag = " ⚠" if name in confirm else ""
            desc = " ".join(str(meta.get("description") or "").split())
            out.append(f"### `{name}`{flag}\n")
            out.append(f"{desc}\n")
            out.append(f"参数：{_params(schema)}\n")
    return "\n".join(out).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="generate docs/tools.md")
    ap.add_argument("--out", default=str(ROOT / "docs" / "tools.md"))
    ap.add_argument("--check", action="store_true",
                    help="verify the file is up to date (exit 1 when stale)")
    args = ap.parse_args(argv)

    target = Path(args.out)
    fresh = render()
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != fresh:
            print(f"[stale] {target} 与注册表不一致，请运行 python scripts/gen_tools_doc.py",
                  file=sys.stderr)
            return 1
        print(f"[ok] {target} 与注册表一致")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(fresh, encoding="utf-8")
    print(f"[ok] 已生成 {target}（{fresh.count(chr(10) + '### ')} 个工具）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
