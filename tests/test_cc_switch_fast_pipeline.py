"""Tests for CC Switch sub-second fast pipeline and dispatch."""

import sqlite3
from unittest.mock import patch


def test_update_cc_switch_provider_remark_db_fallback(tmp_path):
    from uiu.fast_pipeline import update_cc_switch_provider_remark

    # Create dummy CC Switch DB
    db_file = tmp_path / "cc-switch.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE providers (id TEXT, name TEXT, notes TEXT)")
    cur.execute("INSERT INTO providers VALUES ('1', 'Zhipu GLM', 'old_notes')")
    conn.commit()
    conn.close()

    with patch("uiu.window_manager.find_window", return_value=None):
        res = update_cc_switch_provider_remark(
            "Zhipu GLM",
            "test_remark_456",
            db_path_override=str(db_file),
        )
        assert "Zhipu GLM" in res
        assert "test_remark_456" in res
        assert "数据库校验成功" in res

    # Verify DB content directly
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT notes FROM providers WHERE name='Zhipu GLM'")
    assert cur.fetchone()[0] == "test_remark_456"
    conn.close()


def test_desktop_tools_dispatch_update_cc_switch():
    from uiu.desktop_tools import dispatch_tool

    with patch("uiu.fast_pipeline.update_cc_switch_provider_remark", return_value="mock_report_ok") as mock_fn:
        out = dispatch_tool("update_cc_switch_provider_remark", {"provider_name": "Zhipu GLM", "new_remark": "123"})
        assert out == "mock_report_ok"
        mock_fn.assert_called_once_with(provider_name="Zhipu GLM", new_remark="123")
