"""Tests for unified browser tools connecting to host browser session."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from uiu.browser_tools import (
    _page,
    browser_click,
    browser_fill,
    browser_navigate,
    browser_open,
    browser_snapshot,
)


def test_browser_tools_with_active_session():
    mock_session = MagicMock()
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.title.return_value = "Example Page"
    mock_page.url = "https://example.com"
    mock_session.get_active_page.return_value = mock_page

    with patch("uiu.browser_connect.is_cdp_ready", return_value=True), \
         patch("uiu.browser_connect.get_active_browser_session", return_value=mock_session):

        # Test _page() resolution to host session
        p = _page()
        assert p == mock_page

        # Test browser_navigate
        res_nav = browser_navigate("https://example.com/test")
        assert "[ok]" in res_nav
        mock_page.goto.assert_called_with("https://example.com/test", timeout=30000)

        # Test browser_snapshot
        mock_page.accessibility.snapshot.return_value = {
            "role": "button",
            "name": "Submit",
            "ref": "btn1",
            "children": [],
        }
        res_snap = browser_snapshot()
        assert "button" in res_snap
        assert "Submit" in res_snap

        # Test browser_click
        mock_locator = MagicMock()
        mock_page.locator.return_value = mock_locator
        res_click = browser_click("btn1")
        assert "[ok]" in res_click

        # Test browser_fill
        res_fill = browser_fill("input1", "hello text")
        assert "[ok]" in res_fill


def test_browser_open():
    with patch("uiu.system_tools.open_url", return_value="[ok] opened") as mock_open:
        res = browser_open("https://example.com")
        assert res == "[ok] opened"
        mock_open.assert_called_once_with("https://example.com")
