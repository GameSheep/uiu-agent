"""Headless TUI preview renderer (scripts/tui_preview.py) smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_preview_script_renders_one_state(tmp_path):
    from scripts.tui_preview import main

    rc = main(["--only", "welcome", "--svg-only", "--out", str(tmp_path / "preview")])
    assert rc == 0
    svg = (tmp_path / "preview" / "welcome.svg")
    assert svg.exists()
    body = svg.read_text(encoding="utf-8")
    assert "uiu" in body
    assert not (tmp_path / "preview" / "_scratch").exists(), "scratch workspace cleaned up"


def test_preview_script_rejects_unknown_state(tmp_path):
    from scripts.tui_preview import main

    assert main(["--only", "nope", "--svg-only", "--out", str(tmp_path)]) == 2
