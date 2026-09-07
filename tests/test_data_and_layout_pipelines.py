"""Tests for Multi-Modal Clipboard & Smart Window Layout Engines."""

import json
import pytest
from PIL import Image
from uiu.data_pipeline import (
    clipboard_get_text,
    clipboard_set_text,
    clipboard_set_image,
    clipboard_set_table,
    clipboard_parse_table,
    preserve_clipboard,
)
from uiu.layout_manager import (
    get_work_area,
    save_window_layout,
    restore_window_layout,
)
from uiu.desktop_tools import dispatch_tool


def test_clipboard_text_roundtrip():
    test_msg = "uiu-agent-test-clipboard-123456"
    res = clipboard_set_text(test_msg)
    assert res.startswith("[ok]")

    got = clipboard_get_text()
    assert got == test_msg


def test_preserve_clipboard_context_manager():
    # Set initial clipboard
    clipboard_set_text("USER_ORIGINAL_CLIPBOARD_DATA")

    with preserve_clipboard():
        # Temporary agent write
        clipboard_set_text("AGENT_INTERMEDIATE_SECRET")
        assert clipboard_get_text() == "AGENT_INTERMEDIATE_SECRET"

    # After exiting context manager, original clipboard must be restored
    assert clipboard_get_text() == "USER_ORIGINAL_CLIPBOARD_DATA"


def test_clipboard_image_dib():
    img = Image.new("RGB", (64, 64), color=(0, 255, 0))
    res = clipboard_set_image(img)
    assert res.startswith("[ok]")
    assert "CF_DIB" in res


def test_clipboard_table_serialization_and_parsing():
    sample_data = [
        {"name": "Zhipu", "model": "GLM-4", "status": "active"},
        {"name": "OpenAI", "model": "GPT-4o", "status": "ready"},
    ]

    # 1. Test TSV
    tsv_res = clipboard_set_table(sample_data, format_type="tsv")
    assert tsv_res.startswith("[ok]")
    parsed_tsv = clipboard_parse_table()
    assert len(parsed_tsv) == 2
    assert parsed_tsv[0]["name"] == "Zhipu"
    assert parsed_tsv[1]["model"] == "GPT-4o"

    # 2. Test Markdown table
    md_res = clipboard_set_table(sample_data, format_type="markdown")
    assert md_res.startswith("[ok]")
    parsed_md = clipboard_parse_table()
    assert len(parsed_md) == 2
    assert parsed_md[0]["name"] == "Zhipu"

    # 3. Test JSON parsing
    json_text = json.dumps(sample_data)
    parsed_json = clipboard_parse_table(json_text)
    assert len(parsed_json) == 2
    assert parsed_json[0]["name"] == "Zhipu"


def test_layout_work_area():
    bounds = get_work_area()
    assert len(bounds) == 4
    x, y, w, h = bounds
    assert w > 200 and h > 200


def test_layout_save_and_restore():
    # Calling with empty or non-existent list returns cleanly
    records = save_window_layout(["__NON_EXISTENT_APP_XYZ__"])
    assert isinstance(records, list)

    res = restore_window_layout(records)
    assert res.startswith("[ok]")


def test_desktop_tools_clipboard_and_layout_dispatch():
    # Test clipboard_data_pipeline tool
    res_set = dispatch_tool(
        "clipboard_data_pipeline",
        {
            "mode": "set_table",
            "table_data": [{"colA": "1", "colB": "2"}],
            "format": "tsv",
        },
    )
    assert res_set.startswith("[ok]")

    res_parse = dispatch_tool(
        "clipboard_data_pipeline",
        {"mode": "parse_table"},
    )
    assert res_parse.startswith("[ok]")
    assert "colA" in res_parse

    # Test window_layout_tile dispatch for non-existent window
    res_layout = dispatch_tool(
        "window_layout_tile",
        {"app1": "__NON_EXISTENT_WINDOW_XYZ__", "position": "left"},
    )
    assert "[error]" in res_layout or "[ok]" in res_layout
