"""Shared fixtures: make `uiu` importable, isolate cwd per test."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture()
def tmp_cwd(tmp_path, monkeypatch):
    """Run the test with cwd inside a temp dir (tools resolve relative paths here)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UIU_WORKSPACE", str(tmp_path / "workspace"))
    return tmp_path


@pytest.fixture(autouse=True)
def reset_confirm_handler():
    """Ensure confirm and clarify handlers are cleanly reset before and after every test."""
    try:
        from uiu.confirm import set_confirm_handler
        set_confirm_handler(None)
    except Exception:
        pass
    try:
        from uiu.clarify import set_ask_handler
        set_ask_handler(None)
    except Exception:
        pass
    yield
    try:
        from uiu.confirm import set_confirm_handler
        set_confirm_handler(None)
    except Exception:
        pass
    try:
        from uiu.clarify import set_ask_handler
        set_ask_handler(None)
    except Exception:
        pass
