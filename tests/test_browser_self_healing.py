"""Unit tests for visual self-healing and macro hot-patching interceptor."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from uiu.browser_self_healing import (
    _extract_element_at_point,
    _ocr_find_in_image,
    patch_macro_file,
    resilient_browser_action,
)


def test_patch_macro_file(tmp_path: Path):
    macro_file = tmp_path / "sample_macro.py"
    macro_file.write_text(
        'locator("[data-testid=\'old-submit\']").click()\n',
        encoding="utf-8",
    )

    ok = patch_macro_file(macro_file, "[data-testid='old-submit']", "[data-testid='new-submit-v2']")
    assert ok is True

    updated_content = macro_file.read_text(encoding="utf-8")
    assert "[data-testid='new-submit-v2']" in updated_content
    assert "[data-testid='old-submit']" not in updated_content


def test_resilient_browser_action_tier1_dom():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.is_visible.return_value = True
    mock_page.locator.return_value.first = mock_locator

    step_meta = {
        "action": "click",
        "fingerprint": {
            "testId": "submit-btn",
            "text": "提交",
        },
    }

    res = resilient_browser_action(mock_page, step_meta, dom_timeout_ms=500)
    assert res["success"] is True
    assert res["tier"] == "dom"
    assert res["healed"] is False
    mock_locator.click.assert_called_once()


def test_resilient_browser_action_tier2_visual_ocr_fallback(tmp_path: Path):
    mock_page = MagicMock()

    # Make DOM selectors fail
    mock_locator = MagicMock()
    mock_locator.is_visible.return_value = False
    mock_page.locator.return_value.first = mock_locator

    # Create dummy screenshot bytes
    img = Image.new("RGB", (300, 200), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    mock_page.screenshot.return_value = buf.getvalue()

    # Prepare macro file for hot-patching
    macro_file = tmp_path / "web_macro_test.py"
    macro_file.write_text('step_meta = {"target": "[data-testid=\'broken-btn\']"}', encoding="utf-8")

    step_meta = {
        "action": "click",
        "target": "[data-testid='broken-btn']",
        "fingerprint": {
            "testId": "broken-btn",
            "text": "确认支付",
        },
    }

    fake_ocr_match = {
        "text": "确认支付",
        "cx": 150.0,
        "cy": 100.0,
        "box": [100, 80, 100, 40],
        "score": 0.98,
    }

    with patch("uiu.browser_self_healing._ocr_find_in_image", return_value=fake_ocr_match), \
         patch("uiu.browser_self_healing._extract_element_at_point", return_value={"selector": "#new-pay-btn"}):
        res = resilient_browser_action(mock_page, step_meta, macro_file_path=macro_file, dom_timeout_ms=200)

        assert res["success"] is True
        assert res["tier"] == "visual_healed"
        assert res["healed"] is True
        assert res["new_selector"] == "#new-pay-btn"
        assert res["patched"] is True
        mock_page.mouse.click.assert_called_once_with(150.0, 100.0)

        # Verify disk macro was patched
        updated = macro_file.read_text(encoding="utf-8")
        assert "#new-pay-btn" in updated


def test_resilient_browser_action_tier3_bbox_fallback():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.is_visible.return_value = False
    mock_page.locator.return_value.first = mock_locator

    step_meta = {
        "action": "click",
        "target": "#unknown",
        "fingerprint": {
            "bbox": {"cx": 250, "cy": 350},
        },
    }

    with patch("uiu.browser_self_healing._ocr_find_in_image", return_value=None):
        res = resilient_browser_action(mock_page, step_meta, dom_timeout_ms=100)
        assert res["success"] is True
        assert res["tier"] == "bbox_fallback"
        assert res["coords"] == (250, 350)
        mock_page.mouse.click.assert_called_once_with(250, 350)
