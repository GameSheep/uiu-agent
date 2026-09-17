"""Shared fixtures: make `uiu` importable, isolate cwd per test."""

import getpass
import os
import pathlib
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _pytest_tmp_root_usable() -> bool:
    """Can pytest use its default tmp root?

    A previous run on a broken environment can leave an unreadable
    `pytest-of-<user>` directory behind (deny-all ACL, undeletable without
    admin). pytest then dies on os.scandir before any test runs, so fall back
    to a workspace-local root in that case.
    """
    root = Path(tempfile.gettempdir()) / f"pytest-of-{getpass.getuser()}"
    if not root.exists():
        return True
    try:
        with os.scandir(root) as it:
            list(it)
        return True
    except OSError:
        return False


if not os.environ.get("PYTEST_DEBUG_TEMPROOT") and not _pytest_tmp_root_usable():
    fallback = ROOT / ".pytest-tmp"
    shutil.rmtree(fallback, ignore_errors=True)
    fallback.mkdir(parents=True, exist_ok=True)
    os.environ["PYTEST_DEBUG_TEMPROOT"] = str(fallback)


if sys.platform == "win32":
    # Windows + some sandboxes turn mkdir(mode=0o700) into a deny-all ACL: the
    # directory is created but *nobody* can write into it — not even the process
    # that just made it. pytest's tmp_path (and tempfile.mkdtemp) both use 0o700,
    # so without this every tmp_path test fails with PermissionError.
    #
    # POSIX mode bits on Windows only map to the read-only attribute anyway
    # (0o700 → writable), so normalising the mode is a no-op on healthy machines
    # and the difference is unobservable for tests.
    _real_os_mkdir = os.mkdir
    _real_path_mkdir = pathlib.Path.mkdir

    def _os_mkdir(path, mode=0o777, *args, **kwargs):
        return _real_os_mkdir(path, 0o777, *args, **kwargs)

    def _path_mkdir(self, mode=0o777, parents=False, exist_ok=False):
        return _real_path_mkdir(self, 0o777, parents=parents, exist_ok=exist_ok)

    os.mkdir = _os_mkdir
    pathlib.Path.mkdir = _path_mkdir


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
