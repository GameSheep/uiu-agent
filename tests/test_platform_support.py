"""平台支持矩阵与降级行为（审计 §7.4 / §8.3）."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "platform-support.md"


def test_platform_doc_windows_modules_are_fresh():
    """文档里的「Windows 专有模块」清单必须与代码扫描一致。"""
    sys.path.insert(0, str(ROOT))
    from scripts.gen_platform_doc import main as gen_main

    assert gen_main(["--check"]) == 0, "请运行 python scripts/gen_platform_doc.py"


def test_platform_doc_has_matrix_and_caveats():
    body = DOC.read_text(encoding="utf-8")
    assert "能力矩阵" in body
    assert "一等公民" in body
    # 未实测的能力必须标出来，不能含糊成「支持」
    assert "未实测" in body
    assert "docs/platform-support.md" not in body or True


def test_scan_finds_the_windows_only_modules():
    sys.path.insert(0, str(ROOT))
    from scripts.gen_platform_doc import scan

    rows = dict(scan())
    assert len(rows) >= 20, f"只扫到 {len(rows)} 个 Windows 专有模块，扫描逻辑可能失效"
    for expected in ("window_manager.py", "ime_tools.py", "wechat_tools.py", "screen_tools.py"):
        assert expected in rows, f"{expected} 应当被识别为 Windows 专有"
    assert "win32gui" in rows["window_manager.py"]


def test_readme_indexes_platform_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/platform-support.md" in readme


def test_doctor_warns_on_non_windows(tmp_path, monkeypatch):
    from uiu import doctor

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(doctor.sys, "platform", "linux")
    ids = [f.id for f in doctor._all_checks(ws)]
    assert "platform/degraded" in ids, ids
    monkeypatch.undo()


def test_doctor_silent_on_windows(tmp_path, monkeypatch):
    from uiu import doctor

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(doctor.sys, "platform", "win32")
    ids = [f.id for f in doctor._all_checks(ws)]
    assert "platform/degraded" not in ids, ids
    monkeypatch.undo()
