"""npm 包内容契约：发布出去的 tarball 必须包含运行时真正 require 的文件。

为什么单独拉一条：`package.json` 的 `files` 是个**白名单**，加了新目录却忘了登记，
本地 `node bin/install.js` 一切正常（因为源码树里文件都在），
但用户 `npm install` 拿到的 tarball 里缺文件 → MODULE_NOT_FOUND → **整个 npm 通道不可用**。
这个坑真发生过：`files` 只有 `["bin/"]`，而 `bin/install.js` 要 require `../lib/version`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NPM = ROOT / "npm"
# npm 无论 files 怎么写都会包含的文件
_ALWAYS_INCLUDED = {"package.json", "readme", "readme.md", "license", "licence"}


def _package() -> dict:
    return json.loads((NPM / "package.json").read_text(encoding="utf-8"))


def _included(rel: str, files: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    if rel.lower() in _ALWAYS_INCLUDED or Path(rel).name.lower() in _ALWAYS_INCLUDED:
        return True
    for entry in files:
        entry = entry.replace("\\", "/").rstrip("/")
        if rel == entry or rel.startswith(entry + "/"):
            return True
    return False


def _required_paths() -> list[tuple[str, str]]:
    """(谁 require 的, 需要哪个文件)。"""
    out: list[tuple[str, str]] = []
    for js in sorted(NPM.rglob("*.js")):
        if "node_modules" in js.parts:
            continue
        body = js.read_text(encoding="utf-8")
        for m in re.finditer(r"""require\(\s*["'](\.[^"']+)["']\s*\)""", body):
            target = (js.parent / m.group(1)).resolve()
            for cand in (target, target.with_suffix(".js"), target.with_suffix(".json")):
                if cand.exists() and NPM.resolve() in cand.parents:
                    out.append((str(js.relative_to(NPM)), str(cand.relative_to(NPM))))
                    break
    return out


def test_package_json_files_cover_every_required_module():
    files = _package().get("files") or []
    assert files, "package.json 没有 files 白名单（那就该显式说明：全部包含）"
    missing = [(who, need) for who, need in _required_paths() if not _included(need, files)]
    assert not missing, (
        "这些文件会被 npm 排除，但运行时 require 它们 → 用户装完必崩：\n  "
        + "\n  ".join(f"{who} → {need}" for who, need in missing)
        + f"\n（当前 files = {files}）")


def test_bin_entries_exist_and_are_shipped():
    pkg = _package()
    files = pkg.get("files") or []
    bins = pkg.get("bin") or {}
    assert bins, "package.json 没有 bin 入口"
    for name, rel in bins.items():
        path = NPM / rel
        assert path.exists(), f"bin 入口 {name} 指向不存在的文件 {rel}"
        assert _included(rel, files), f"bin 入口 {rel} 不在 files 白名单里（用户装不到）"
        assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env node"), \
            f"{rel} 缺少 shebang"


def test_postinstall_hook_is_present():
    pkg = _package()
    hook = (pkg.get("scripts") or {}).get("postinstall", "")
    assert "install.js" in hook, f"缺少 postinstall 钩子：{hook!r}"
    assert _included("bin/install.js", pkg.get("files") or [])


def test_version_mapper_is_shipped_and_self_tests():
    """lib/version.js 是 npm↔PyPI 版本映射，必须随包发出且自检通过。"""
    files = _package().get("files") or []
    assert _included("lib/version.js", files), "lib/version.js 不在 files 白名单里"
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("本机没有 node")
    proc = subprocess.run([node, str(NPM / "lib" / "version.js")],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
