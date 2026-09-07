"""Tests for hierarchical dual-agent orchestration (Microsoft UFO pattern)."""

from unittest.mock import patch


def test_host_agent_decompose_compound_goal():
    from uiu.hierarchical_agent import HostAgent

    host = HostAgent()
    goal = "把 CC Switch 备注修改为 123 然后发微信给文件传输助手通知已更新"
    subtasks = host.decompose_goal(goal)

    assert len(subtasks) == 2
    assert subtasks[0].app_name == "CC Switch"
    assert "CC Switch" in subtasks[0].goal
    assert subtasks[1].app_name == "微信"
    assert "微信" in subtasks[1].goal


def test_app_agent_routing_cc_switch():
    from uiu.hierarchical_agent import AppAgent, AppSubTask

    agent = AppAgent("CC Switch")
    subtask = AppSubTask(app_name="CC Switch", goal="修改 Zhipu GLM 备注为 456")

    with patch("uiu.fast_pipeline.update_cc_switch_provider_remark", return_value="[CC Switch] 成功更新") as mock_fn, \
         patch("uiu.window_manager.find_window", return_value=None), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        res = agent.execute(subtask)
        assert res.status == "success"
        assert "成功更新" in res.result
        mock_fn.assert_called_once()


def test_app_agent_routing_wechat():
    from uiu.hierarchical_agent import AppAgent, AppSubTask

    agent = AppAgent("微信")
    subtask = AppSubTask(app_name="微信", goal="发微信给张三内容为测试完成")

    with patch("uiu.wechat_tools.send_wechat", return_value="[ok] 已发送") as mock_fn, \
         patch("uiu.window_manager.find_window", return_value=None), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        res = agent.execute(subtask)
        assert res.status == "success"
        assert "[ok]" in res.result
        mock_fn.assert_called_once()


def test_host_agent_execute_goal_end_to_end():
    from uiu.hierarchical_agent import HostAgent, hierarchical_execute

    with patch("uiu.fast_pipeline.update_cc_switch_provider_remark", return_value="[CC Switch] 备注已更新"), \
         patch("uiu.wechat_tools.send_wechat", return_value="[ok] 消息已送达"), \
         patch("uiu.window_manager.find_window", return_value=None), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        host = HostAgent()
        out = host.execute_goal("把 CC Switch 备注修改为 123 然后发微信给文件传输助手通知已更新")
        assert out["success"] is True
        assert out["subtasks_count"] == 2
        assert len(out["timeline"]) == 2

        # Test string tool wrapper
        report = hierarchical_execute("把 CC Switch 备注修改为 123 然后发微信给文件传输助手通知已更新")
        assert "[分级协同执行报告] 全部成功" in report
        assert "第 1 阶段 [CC Switch]" in report
        assert "第 2 阶段 [微信]" in report


def test_desktop_tools_dispatch_hierarchical_execute():
    from uiu.desktop_tools import dispatch_tool

    with patch("uiu.hierarchical_agent.hierarchical_execute", return_value="mock_hierarchical_ok") as mock_fn:
        res = dispatch_tool("hierarchical_execute", {"goal": "复合目标测试"})
        assert res == "mock_hierarchical_ok"
        mock_fn.assert_called_once_with(goal="复合目标测试")
