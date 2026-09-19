"""退出码契约：失败必须非 0（P0-5 同类）。

已经栽过三次，都是同一个形状——「打印一句结果 + 无条件 return 0」：

    uiu serve          没起来却返回 0
    uiu restore        非交互下静默不做事却返回 0
    uiu skills install DNS 挂了、打印 [error]，仍然返回 0

脚本与 CI 会据此以为成功。这个文件盯住它，并用静态扫描防止再写出第四处。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "uiu"

# 「print(某个函数调用) 后紧跟 return 0」——返回值可能是 [error] 文本，必须映射退出码。
# 允许清单：这些函数只返回展示用的文本，不会失败。
_PRINT_CALL_OK = {
    "_plugins_dir",     # 只返回路径
    "macro_list",       # 只是列出宏
}


def test_skill_install_failure_returns_nonzero(tmp_path, capsys):
    """无法识别的 identifier：必须非 0（不需要网络）。"""
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()

    rc = main(["--workspace", str(ws), "skills", "install", "!!!not-a-valid-identifier!!!"])
    captured = capsys.readouterr()
    assert rc != 0, f"安装失败却返回 0：{captured.out}"
    assert "[error]" in (captured.out + captured.err)


def test_skill_install_success_returns_zero(tmp_path, capsys, monkeypatch):
    from uiu import skill_installer
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(skill_installer, "install_skill",
                        lambda *a, **k: "[ok] 已安装 demo")
    assert main(["--workspace", str(ws), "skills", "install", "owner/repo"]) == 0
    assert "已安装" in capsys.readouterr().out


def test_skill_search_failure_returns_nonzero(tmp_path, capsys, monkeypatch):
    from uiu import skill_installer
    from uiu.main import main

    ws = tmp_path / "ws"
    assert main(["--workspace", str(ws), "init"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(skill_installer, "search_skills",
                        lambda *a, **k: "[error] 搜索失败: URLError")
    rc = main(["--workspace", str(ws), "skills", "search", "x"])
    captured = capsys.readouterr()
    assert rc != 0, captured.out
    assert "[error]" in (captured.out + captured.err)


def test_ok_or_error_helper_semantics():
    from uiu import cli_shared

    assert cli_shared._ok_or_error("[ok] 成功") == 0
    assert cli_shared._ok_or_error("[error] 失败") == 1
    assert cli_shared._ok_or_error("  [error] 前面有空格也算") == 1
    assert cli_shared._ok_or_error("[ok] 里面提到 [error] 但开头是 ok") == 0


def test_no_print_then_return_zero_anti_pattern():
    """静态扫描：`print(可能失败的调用)` 后面直接 `return 0` 是这次栽过的形状。"""
    pattern = re.compile(r"^\s*print\(([A-Za-z_][\w.]*)\(.*\)\)\s*$")
    offenders = []
    for path in sorted(SRC.glob("cli_*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if not m:
                continue
            func = m.group(1).split(".")[-1]
            if func in _PRINT_CALL_OK:
                continue
            nxt = next((ln.strip() for ln in lines[i + 1:] if ln.strip()), "")
            if nxt == "return 0":
                offenders.append(f"{path.name}:{i + 1}: print({func}(...)) 后直接 return 0")
    assert not offenders, (
        "这些地方会把失败报成成功；请改用 _ok_or_error(...) 或显式判断：\n  "
        + "\n  ".join(offenders))
