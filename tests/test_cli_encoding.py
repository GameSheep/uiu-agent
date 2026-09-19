"""CLI 在**真实控制台编码**下不许崩（中文 Windows 是 GBK）。

为什么要有这个文件：`uiu publish` 和 `uiu skills search` 都曾在 GBK 控制台上
死于 `UnicodeEncodeError`——文案里有 ⭐ / ✓ 这类不在 GBK 码表里的符号。

**pytest 的 capsys 测不出这类问题**：它捕获的是**文本**，真实控制台编码的是**字节**。
所以这里必须起子进程 + 指定 `PYTHONIOENCODING`，逐个把命令跑一遍。

防线有两层：
1. `cli_io.configure_stdio()` 在入口把 stdout/stderr 的 errors 改成 replace（全局兜底）；
2. 容易出现 `?` 的符号顺手换成 ASCII（如 ⭐ → *）。
本文件盯的是「有没有真的崩」，所以它同时保护这两层不被回退。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 覆盖各条输出路径：纯文本、表格、--json、以及带符号的那几条
COMMANDS = [
    ["version"],
    ["show"],
    ["doctor", "--lint"],
    ["doctor", "--lint", "--json"],
    ["config", "--list"],
    ["skills", "list"],
    ["skills", "search", "uiu"],          # 曾经崩在 ⭐
    ["channel", "list"],
    ["cron", "list"],
    ["macro", "list"],
    ["sessions", "usage"],
    ["sessions", "list"],
    ["trash"],
    ["trash", "--json"],
    ["audit", "--tail", "3"],
    ["plugins", "list"],
    ["backup", "--list"],
]


@pytest.fixture(scope="module")
def gbk_workspace(tmp_path_factory):
    """给扫荡用的 workspace；只建一次，省掉每条命令的初始化开销。"""
    ws = tmp_path_factory.mktemp("gbk_ws")
    env = {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONPATH": str(ROOT / "src")}
    subprocess.run([sys.executable, "-m", "uiu.main", "--workspace", str(ws), "init"],
                   capture_output=True, env=env, timeout=300)
    return ws


def _run(cmd: list[str], ws: Path, encoding: str = "gbk"):
    env = {**os.environ, "PYTHONIOENCODING": encoding, "PYTHONPATH": str(ROOT / "src"),
           "UIU_WORKSPACE": str(ws)}
    return subprocess.run([sys.executable, "-m", "uiu.main", "--workspace", str(ws), *cmd],
                          capture_output=True, env=env, timeout=300)


@pytest.mark.parametrize("cmd", COMMANDS, ids=lambda c: "_".join(c)[:40])
def test_cli_never_crashes_on_a_gbk_console(cmd, gbk_workspace):
    proc = _run(cmd, gbk_workspace, encoding="gbk")
    err = proc.stderr.decode("gbk", "replace")
    assert "UnicodeEncodeError" not in err, (
        f"`uiu {' '.join(cmd)}` 在 GBK 控制台上编码崩了：\n{err[-500:]}")
    assert "Traceback" not in err, (
        f"`uiu {' '.join(cmd)}` 抛异常了：\n{err[-500:]}")
    assert proc.returncode in (0, 1, 2), f"意外退出码 {proc.returncode}：{err[-300:]}"


def test_configure_stdio_makes_streams_error_tolerant(monkeypatch):
    """兜底本身也要有测试：不能因为某次重构把 reconfigure 去掉。"""
    from uiu import cli_io

    recorded = []

    class FakeStream:
        encoding = "gbk"

        def reconfigure(self, **kw):
            recorded.append(kw)

    monkeypatch.setattr(sys, "stdout", FakeStream())
    monkeypatch.setattr(sys, "stderr", FakeStream())
    cli_io.configure_stdio()
    assert recorded, "configure_stdio 没有对 stdout/stderr 做任何设置"
    assert all(kw.get("errors") == "replace" for kw in recorded), recorded


def test_safe_print_degrades_instead_of_raising(capsys):
    """_safe_print 是真遇到不可编码字符时的第二道防线。"""
    from uiu import cli_io

    class GbkOnly:
        encoding = "gbk"

        def write(self, s):                      # 模拟 GBK 控制台
            s.encode("gbk")                      # 不可编码就抛 UnicodeEncodeError
            return len(s)

        def flush(self):
            pass

    class Stream:
        def __init__(self):
            self.buf = GbkOnly()

        def write(self, s):
            return self.buf.write(s)

        def flush(self):
            self.buf.flush()

        encoding = "gbk"

    cli_io._safe_print("含符号 \u2b50 的一行", Stream())   # 不抛就算过
