"""Unit tests for default browser detection and CDP connection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from uiu.browser_connect import (
    BrowserSession,
    attach_default_browser,
    detect_browser_executable,
    detect_chrome_executable,
    detect_chrome_user_data_dir,
    detect_edge_executable,
    disconnect_browser_session,
    ensure_browser_with_cdp,
    is_cdp_ready,
)


def test_detect_chrome_executable():
    exe = detect_chrome_executable()
    # If Chrome is installed on the machine, exe will be a string ending in chrome.exe
    if exe:
        assert "chrome" in exe.lower()
        assert Path(exe).exists()


def test_detect_edge_executable():
    exe = detect_edge_executable()
    if exe:
        assert "edge" in exe.lower()
        assert Path(exe).exists()


def test_detect_browser_executable():
    exe = detect_browser_executable()
    # At least Chrome or Edge should be detected on standard Windows
    if exe:
        assert Path(exe).exists()


def test_detect_chrome_user_data_dir():
    p = detect_chrome_user_data_dir()
    if p:
        assert isinstance(p, Path)
        assert "Chrome" in str(p)


def test_is_cdp_ready_mock():
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_open.return_value.__enter__.return_value = mock_resp
        assert is_cdp_ready("127.0.0.1", 9222) is True

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert is_cdp_ready("127.0.0.1", 99999) is False


def test_ensure_browser_with_cdp_already_running():
    with patch("uiu.browser_connect.is_cdp_ready", return_value=True), \
         patch("uiu.browser_connect.get_cdp_version_info", return_value={"Browser": "Chrome/120.0"}):
        res = ensure_browser_with_cdp(port=9222)
        assert res["ready"] is True
        assert res["action"] == "already_running"


def test_ensure_browser_with_cdp_not_running_launch():
    with patch("uiu.browser_connect.is_cdp_ready", return_value=False), \
         patch("uiu.browser_connect.is_browser_process_running", return_value=False), \
         patch("uiu.browser_connect.launch_browser_with_cdp", return_value=True):
        res = ensure_browser_with_cdp(port=9222)
        assert res["ready"] is True
        assert res["action"] == "launched"


def test_browser_session_lifecycle():
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_ctx = MagicMock()
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.title.return_value = "Test Page"
    mock_page.url = "https://example.com"
    mock_ctx.pages = [mock_page]

    session = BrowserSession(
        playwright=mock_pw,
        browser=mock_browser,
        context=mock_ctx,
        page=mock_page,
        port=9222,
    )

    assert session.get_active_page() == mock_page
    tabs = session.list_tabs()
    assert len(tabs) == 1
    assert tabs[0]["title"] == "Test Page"

    session.close()
    mock_browser.close.assert_called_once()
    mock_pw.stop.assert_called_once()


def test_dispatch_browser_tools(tmp_path: Path):
    from uiu.desktop_tools import dispatch_tool

    # 1. browser_default_attach
    mock_session = MagicMock()
    mock_page = MagicMock()
    mock_page.title.return_value = "Active Tab"
    mock_page.url = "https://www.google.com"
    mock_session.get_active_page.return_value = mock_page
    mock_session.list_tabs.return_value = [{"title": "Active Tab", "url": "https://www.google.com"}]

    with patch("uiu.browser_connect.ensure_browser_with_cdp", return_value={"ready": True}), \
         patch("uiu.browser_connect.attach_default_browser", return_value=mock_session):
        res = dispatch_tool("browser_default_attach", {"port": 9222})
        assert "[ok]" in res
        assert "Active Tab" in res

    # 2. browser_explore_step (inspect)
    with patch("uiu.browser_connect.get_active_browser_session", return_value=mock_session), \
         patch("uiu.browser_explorer.capture_page_state", return_value={"url": "https://www.google.com", "title": "Google", "elements": [], "element_count": 0}):
        res_inspect = dispatch_tool("browser_explore_step", {"action": "inspect"})
        assert "Google" in res_inspect

    # 3. browser_compile_macro
    compile_args = {
        "name": "search_demo",
        "description": "demo search",
        "start_url": "https://www.google.com",
        "steps": [{"action": "click", "target": "#btn"}],
        "parameters": [],
    }
    with patch("uiu.browser_compiler.save_and_register_browser_macro", return_value=("search_demo", tmp_path / "search_demo.py")):
        res_compile = dispatch_tool("browser_compile_macro", compile_args)
        assert "[ok]" in res_compile
        assert "search_demo" in res_compile

    # 4. browser_macro_run
    with patch("uiu.browser_compiler.run_browser_macro", return_value="[ok] 宏运行完成"):
        res_run = dispatch_tool("browser_macro_run", {"name": "search_demo", "kwargs": {}})
        assert res_run == "[ok] 宏运行完成"
