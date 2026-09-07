"""Tests for Episodic Memory and Macro Recall."""

from unittest.mock import patch
from uiu.episodic_memory import record_episode, find_matching_macro, list_episodes


def test_record_and_find_episodic_macro(tmp_path):
    mem_file = tmp_path / "episodic_memory.json"
    with patch("uiu.episodic_memory._get_episodic_file", return_value=mem_file):
        ep = record_episode(
            goal="修改 CC Switch 供应商备注",
            target_app="CC Switch",
            macro_name="update_cc_switch_provider_remark",
            parameters=["provider_name", "new_remark"],
            keywords=["cc switch", "zhipu glm", "备注", "供应商"],
        )
        assert ep["macro_name"] == "update_cc_switch_provider_remark"
        assert len(list_episodes()) == 1

        # Search by query
        match1 = find_matching_macro("帮我改一下 CC Switch 的备注")
        assert match1 is not None
        assert match1["macro_name"] == "update_cc_switch_provider_remark"
        assert match1["match_score"] > 0.5

        # Unrelated query should not match
        match2 = find_matching_macro("完全不相干的天气查询")
        assert match2 is None


def test_desktop_tools_macro_dispatch():
    from uiu.desktop_tools import dispatch_tool

    with patch("uiu.trajectory_compiler.save_and_register_macro", return_value=("mock_macro", "path/to/mock.py")):
        res = dispatch_tool("macro_auto_compile", {
            "name": "mock_macro",
            "steps": [{"action": "click", "x": 10, "y": 20}],
        })
        assert "[ok]" in res
        assert "mock_macro" in res

    with patch("uiu.trajectory_compiler.run_compiled_macro", return_value="macro_executed_100ms"):
        res = dispatch_tool("macro_fast_run", {"macro_name": "mock_macro"})
        assert res == "macro_executed_100ms"
