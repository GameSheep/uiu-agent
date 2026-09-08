"""Unit tests for browser trajectory to Playwright macro compiler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from uiu.browser_compiler import (
    COMPILED_BROWSER_MACROS,
    compile_browser_trajectory_to_python,
    run_browser_macro,
    save_and_register_browser_macro,
)
from uiu.browser_explorer import BrowserTrajectory


def test_compile_browser_trajectory_to_python_syntax():
    traj = BrowserTrajectory(
        name="search_and_click",
        description="Search keyword and click first result",
        start_url="https://www.google.com",
        steps=[
            {
                "action": "fill",
                "target": "textarea[name='q']",
                "value": "keyword",
                "fingerprint": {"testId": "search-input", "name": "q"},
            },
            {
                "action": "click",
                "target": "input[name='btnK']",
                "value": "",
                "fingerprint": {"testId": "search-submit", "text": "Google 搜索"},
            },
        ],
        parameters=["keyword"],
    )

    code = compile_browser_trajectory_to_python(traj)

    # 1. Must be valid Python syntax
    compiled = compile(code, "<string>", "exec")
    assert compiled is not None

    # 2. Check function signature & docstring
    assert "def search_and_click(keyword) -> str:" in code
    assert "Search keyword and click first result" in code
    assert "attach_default_browser" in code
    assert "resilient_browser_action" in code
    assert "step_meta_1" in code
    assert "step_meta_2" in code


def test_save_and_register_browser_macro(tmp_path: Path):
    traj = BrowserTrajectory(
        name="quick_hello",
        description="A quick mock macro",
        start_url="https://example.com",
        steps=[
            {
                "action": "click",
                "target": "#btn",
                "value": "",
                "fingerprint": {"id": "btn"},
            }
        ],
    )

    fn_name, target_file = save_and_register_browser_macro(traj, save_dir=tmp_path)
    assert fn_name == "quick_hello"
    assert target_file.exists()
    assert fn_name in COMPILED_BROWSER_MACROS


def test_run_browser_macro_execution():
    mock_fn = MagicMock(return_value="[ok] 执行成功")
    COMPILED_BROWSER_MACROS["test_macro_run"] = mock_fn

    res = run_browser_macro("test_macro_run", param1="value1")
    assert res == "[ok] 执行成功"
    mock_fn.assert_called_once_with(param1="value1")
