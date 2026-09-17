"""Unit tests for exploratory step engine and composite fingerprinting."""

from __future__ import annotations

from unittest.mock import MagicMock

import importlib.util as _importlib_util

import pytest

if _importlib_util.find_spec("playwright") is None:
    pytest.skip("浏览器测试需要 playwright：pip install uiu[browser]", allow_module_level=True)

from uiu.browser_explorer import (
    BrowserTrajectory,
    TrajectoryRecorder,
    capture_page_state,
    execute_step,
    format_page_state_for_agent,
    resolve_element_locator,
)


def test_capture_page_state():
    mock_page = MagicMock()
    mock_page.url = "https://www.example.com"
    mock_page.title.return_value = "Example Domain"
    mock_page.evaluate.return_value = [
        {
            "ref": 1,
            "tag": "button",
            "role": "button",
            "text": "Submit",
            "testId": "btn-submit",
            "ariaLabel": "Submit Form",
            "id": "submit",
            "name": "btn",
            "css": "#submit",
            "bbox": {"x": 100, "y": 200, "width": 80, "height": 32},
        }
    ]

    state = capture_page_state(mock_page)
    assert state["url"] == "https://www.example.com"
    assert state["title"] == "Example Domain"
    assert state["element_count"] == 1
    assert state["elements"][0]["testId"] == "btn-submit"

    formatted = format_page_state_for_agent(state)
    assert "Example Domain" in formatted
    assert "[1]" in formatted
    assert "btn-submit" in formatted


def test_resolve_element_locator_by_ref():
    mock_page = MagicMock()
    cached = [
        {
            "ref": 1,
            "tag": "button",
            "testId": "search-btn",
            "text": "Search",
        }
    ]

    loc, el = resolve_element_locator(mock_page, 1, cached_elements=cached)
    assert loc is not None
    assert el["testId"] == "search-btn"
    mock_page.locator.assert_called_with('[data-testid="search-btn"]')


def test_resolve_element_locator_by_fingerprint():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_page.locator.return_value.first = mock_locator

    fp = {
        "testId": "login-submit",
        "text": "登录",
        "css": "#login",
    }
    loc, resolved_fp = resolve_element_locator(mock_page, fp)
    assert loc is not None
    assert resolved_fp["testId"] == "login-submit"
    mock_page.locator.assert_called_with('[data-testid="login-submit"]')


def test_execute_step_click():
    mock_page = MagicMock()
    mock_page.url = "https://example.com/step1"
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_page.locator.return_value.first = mock_locator

    res = execute_step(
        page=mock_page,
        action="click",
        target="#submit-btn",
    )
    assert res["success"] is True
    assert res["action"] == "click"
    mock_locator.click.assert_called_once()


def test_execute_step_fill():
    mock_page = MagicMock()
    mock_page.url = "https://example.com/login"
    mock_locator = MagicMock()
    mock_locator.count.return_value = 1
    mock_page.locator.return_value.first = mock_locator

    res = execute_step(
        page=mock_page,
        action="fill",
        target="#username",
        value="admin",
        clear_before=True,
    )
    assert res["success"] is True
    assert res["action"] == "fill"
    assert res["value"] == "admin"
    mock_locator.fill.assert_called_once_with("admin", timeout=8000.0)


def test_trajectory_recorder():
    recorder = TrajectoryRecorder(name="test_traj", description="Test flow")
    step1 = {
        "success": True,
        "action": "fill",
        "target": "#kw",
        "value": "playwright",
        "fingerprint": {"testId": "search-input"},
        "navigated": False,
        "url_before": "https://www.baidu.com",
        "url_after": "https://www.baidu.com",
    }
    step2 = {
        "success": True,
        "action": "click",
        "target": "#su",
        "value": "",
        "fingerprint": {"testId": "search-button"},
        "navigated": True,
        "url_before": "https://www.baidu.com",
        "url_after": "https://www.baidu.com/s?wd=playwright",
    }

    recorder.record_step(step1)
    recorder.record_step(step2)

    traj = recorder.export_trajectory(parameters=["query"])
    assert traj.name == "test_traj"
    assert len(traj.steps) == 2
    assert traj.start_url == "https://www.baidu.com"
    assert traj.parameters == ["query"]
