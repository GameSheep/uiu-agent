#!/usr/bin/env python
"""Maintain the generated parts of docs/platform-support.md.

平台矩阵的**散文**是手写的，但「哪些模块依赖 Windows 专有库」必须来自代码扫描，
否则今天写 12 个、明天涨到 30 个就又成假话（审计 §7.4/§8.3）。

用法：
    python scripts/gen_platform_doc.py            # 用扫描结果刷新文档里的标记块
    python scripts/gen_platform_doc.py --check    # CI：不一致就退出 1
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "platform-support.md"
BEGIN = "<!-- windows-only:begin -->"
END = "<!-- windows-only:end -->"

_WIN_TOP = {
    "win32api", "win32con", "win32gui", "win32clipboard", "win32com", "win32process",
    "win32event", "win32file", "win32security", "win32service", "pythoncom",
    "pywinauto", "uiautomation", "msvcrt", "pyautogui",
}
_ALSO = ("screen_ocr",)


def scan() -> list[tuple[str, list[str]]]:
    """返回 [(模块相对路径, [命中的 Windows 专有库])]，按路径排序。"""
    src = ROOT / "src" / "uiu"
    rows: list[tuple[str, list[str]]] = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in _WIN_TOP or alias.name.startswith("ctypes.wintypes"):
                        hits.add("ctypes.wintypes" if alias.name.startswith("ctypes.wintypes") else top)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in _WIN_TOP or node.module.startswith("ctypes.wintypes"):
                    hits.add("ctypes.wintypes" if node.module.startswith("ctypes.wintypes") else top)
        if re.search(r"(^|\s)import ctypes\b|from ctypes\b", text):
            hits.add("ctypes")
        for name in _ALSO:
            if re.search(rf"^\s*(import|from)\s+{name}\b", text, re.M):
                hits.add(name)
        if hits:
            rows.append((str(path.relative_to(src)), sorted(hits)))
    return rows


def block() -> str:
    rows = scan()
    lines = [BEGIN, f"共 **{len(rows)}** 个模块直接依赖 Windows 专有库/接口：", ""]
    for name, hits in rows:
        lines.append(f"- `{name}` — {', '.join(hits)}")
    lines.append(END)
    return "\n".join(lines)


def render(current: str) -> str:
    if BEGIN not in current or END not in current:
        raise SystemExit(f"文档缺少标记块 {BEGIN} / {END}")
    head, rest = current.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + block() + tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="refresh docs/platform-support.md")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if not current:
        print(f"[error] 找不到 {DOC}", file=sys.stderr)
        return 2
    fresh = render(current)
    if args.check:
        if fresh != current:
            print("[stale] docs/platform-support.md 的 Windows 专有模块清单已过期，"
                  "请运行 python scripts/gen_platform_doc.py", file=sys.stderr)
            return 1
        print("[ok] docs/platform-support.md 与代码一致")
        return 0
    DOC.write_text(fresh, encoding="utf-8")
    print(f"[ok] 已刷新 {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
