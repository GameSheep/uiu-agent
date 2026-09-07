"""Test suite for the 8 extended agent capabilities in uiu-agent."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

import uiu.tools as tools
from uiu.window_manager import _find_installed_app, open_or_focus_app, launch_application
from uiu.browser_login import _eval_arithmetic, solve_captcha_ocr
from uiu.monitor_tools import check_outlook_emails, check_wechat_messages, check_notifications
from uiu.system_tools import software_inventory
from uiu.file_tools import (
    file_copy,
    file_move,
    file_get_content,
    directory_list,
    file_delete,
)
from uiu.agent_tools import launch_agent_terminal, agent_file_editor
from uiu.screen_watcher import screen_watch_and_react, web_frequent_monitor
from uiu.email_gui import send_email_via_gui
from uiu.cron import cron_add_job, cron_list_jobs, cron_remove_job


# 1. 软件一键打开与置顶 (Requirements 1 & 8)
def test_app_discovery_and_launch_guards():
    # Aliases resolve to known executables/shortcuts/protocols
    np = _find_installed_app("notepad")
    assert np is not None and "notepad" in np.lower()

    chrome = _find_installed_app("chrome")
    assert chrome is not None and "chrome" in chrome.lower()

    # Shell injection is blocked
    assert launch_application("notepad & calc").startswith("[error]")
    assert launch_application("calc | dir").startswith("[error]")
    assert launch_application("javascript:alert(1)").startswith("[error]")
    assert launch_application("").startswith("[error]")

    # Empty target handling
    assert open_or_focus_app("").startswith("[error]")


# 2. Chrome 自动登录与图片验证码 OCR 智能识别 (Requirement 2)
def test_captcha_arithmetic_evaluation():
    assert _eval_arithmetic("3 + 5 = ?") == "8"
    assert _eval_arithmetic("15 - 7 =") == "8"
    assert _eval_arithmetic("6 x 9") == "54"
    assert _eval_arithmetic("24 / 4") == "6"
    assert _eval_arithmetic("18 ÷ 2") == "9"
    assert _eval_arithmetic("xyz987") is None


def test_solve_captcha_ocr_interface():
    # Calling on empty/missing area returns structured JSON response with success=False
    res_str = solve_captcha_ocr(region=[0, 0, 50, 20])
    data = json.loads(res_str)
    assert "success" in data


# 3. 新邮件与新消息检测 (Requirement 3)
def test_monitor_tools_execution():
    # Outlook email check returns formatted markdown or clean error
    out = check_outlook_emails(unread_only=True, limit=2)
    assert "[邮件] Outlook 邮件检测" in out or "[warning]" in out or "[error]" in out

    # WeChat check returns formatted markdown or error
    wx_out = check_wechat_messages(unread_only=True)
    assert isinstance(wx_out, str)

    # Unified check
    all_out = check_notifications(target="all")
    assert isinstance(all_out, str)


# 4. 系统软件统计与版本/升级检测 (Requirement 4)
def test_software_inventory():
    # Query with a common keyword
    res = software_inventory(filter_keyword="wechat", check_updates=False, limit=5)
    assert "### [系统软件统计]" in res
    assert "软件名称" in res and "当前版本" in res


# 5. 全功能文件操作与启动 cmd 调度 Agent (Requirement 5)
def test_file_operations(tmp_path):
    f1 = tmp_path / "test1.txt"
    f1.write_text("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n", encoding="utf-8")

    # Slice reading
    content = file_get_content(str(f1), start_line=2, end_line=4)
    assert "Line 2" in content and "Line 4" in content
    assert "Line 1" not in content and "Line 5" not in content

    # Copying
    f2 = tmp_path / "test2.txt"
    res_copy = file_copy(str(f1), str(f2))
    assert res_copy.startswith("[ok]")
    assert f2.exists() and f2.read_text(encoding="utf-8") == f1.read_text(encoding="utf-8")

    # Moving
    f3 = tmp_path / "test3.txt"
    res_move = file_move(str(f2), str(f3))
    assert res_move.startswith("[ok]")
    assert f3.exists() and not f2.exists()

    # Directory listing
    dir_res = directory_list(str(tmp_path), recursive=False)
    assert "test1.txt" in dir_res and "test3.txt" in dir_res

    # Deleting
    del_res = file_delete(str(f3))
    assert del_res.startswith("[ok]")
    assert not f3.exists()


def test_agent_terminal_and_file_editor_guards():
    # Empty inputs
    assert agent_file_editor(file_path="", prompt="fix").startswith("[error]")
    assert agent_file_editor(file_path="foo.py", prompt="").startswith("[error]")


# 6. 高频截图巡检与秒级响应监控 (Requirement 6)
def test_screen_watcher_timeout():
    # Fast test of watch loop timing out after 0.5s
    res = screen_watch_and_react(target_text="__NON_EXISTENT_TXT_XYZ__", interval=0.2, timeout=0.5)
    assert res.startswith("[timeout]") or res.startswith("[ok]")


# 7. 纯 OCR 邮件发送与绝对定时功能 (Requirement 7)
def test_email_gui_validation():
    # Validation of required fields
    assert send_email_via_gui(to="").startswith("[error]")
    assert send_email_via_gui(to="test@test.com", subject="", body="").startswith("[error]")


def test_cron_agent_tools():
    # Create job
    res = cron_add_job(name="pytest_job", schedule="daily 10:00", task="say hello")
    assert res.startswith("[ok]")

    # List jobs
    listing = cron_list_jobs()
    assert "pytest_job" in listing

    # Delete job
    del_res = cron_remove_job("pytest_job")
    assert del_res.startswith("[ok]")


# 8. 验证所有新增工具均成功注册并在 BUILTIN_TOOLS 中 (Requirement 8)
def test_all_new_tools_registered_in_builtin_tools():
    expected_tools = [
        # Req 1 & 8: App open & focus
        "app_open_or_focus",
        # Req 2: Browser login & captcha
        "solve_captcha_ocr",
        "chrome_auto_login",
        # Req 3: Notifications
        "check_outlook_emails",
        "check_wechat_messages",
        "check_notifications",
        # Req 4: Software inventory
        "software_inventory",
        # Req 5: File operations & agent terminal
        "file_copy",
        "file_move",
        "file_get_content",
        "directory_list",
        "file_delete",
        "launch_agent_terminal",
        "agent_file_editor",
        # Req 6: Screen watcher
        "screen_watch_and_react",
        "web_frequent_monitor",
        # Req 7: GUI email & cron
        "send_email_via_gui",
        "cron_add_job",
        "cron_list_jobs",
        "cron_remove_job",
    ]

    for name in expected_tools:
        assert name in tools.BUILTIN_TOOLS, f"Missing tool: {name}"
        assert callable(tools.BUILTIN_TOOLS[name]["fn"]), f"Tool {name} fn not callable"
        assert tools.BUILTIN_TOOLS[name]["def"]["function"]["name"] == name


# 9. 分级局部嗅探与零漂移精确坐标定位 (Requirement 9)
def test_zero_drift_word_and_phrase_matching():
    from uiu.screen_tools import match_text_element

    # 模拟包含时间戳的整行 OCR 结果
    # 如果按整行计算，cx 是 195；如果按 "文件传输助手" 计算，cx 必须是 145.0
    mock_items = [{
        "text": "文件传输助手 13:20",
        "x": 100, "y": 200, "w": 190, "h": 20,
        "cx": 195.0, "cy": 210.0,
        "words": [
            {"text": "文件", "x": 100, "y": 200, "w": 30, "h": 20, "cx": 115.0, "cy": 210.0},
            {"text": "传输", "x": 130, "y": 200, "w": 30, "h": 20, "cx": 145.0, "cy": 210.0},
            {"text": "助手", "x": 160, "y": 200, "w": 30, "h": 20, "cx": 175.0, "cy": 210.0},
            {"text": "13:20", "x": 250, "y": 202, "w": 40, "h": 16, "cx": 270.0, "cy": 210.0},
        ]
    }]

    # 1. 词组精准匹配：必须命中 145.0，杜绝拖向右侧 13:20 的漂移
    match = match_text_element(mock_items, "文件传输助手")
    assert match is not None
    assert match["cx"] == 145.0
    assert match["x"] == 100
    assert match["w"] == 90

    # 2. 单词精准匹配：必须命中具体词的中心坐标
    match_single = match_text_element(mock_items, "助手")
    assert match_single is not None
    assert match_single["cx"] == 175.0

    # 3. 匹配行中非单独 word 的子串（比例插值）
    mock_rapid = [{
        "text": "Settings (Beta)",
        "x": 200, "y": 100, "w": 150, "h": 25,
        "cx": 275.0, "cy": 112.5,
    }]
    match_sub = match_text_element(mock_rapid, "Settings")
    assert match_sub is not None
    assert match_sub["x"] >= 200
    assert match_sub["cx"] < 275.0  # Settings 位于前半部分，中心坐标必须小于整行中心 275.0


def test_hierarchical_sniffing_tiers(monkeypatch):
    from uiu import vision_locator

    calls = []

    def mock_get_screen_elements(region=None):
        calls.append(region)
        if region is not None:
            rx, ry, rw, rh = region
            # Tier 1 命中：围绕鼠标中心 (500, 400) 的周边嗅探区域
            if abs(rx + rw // 2 - 500) < 50:
                return [{"text": "快速保存", "x": 420, "y": 320, "w": 60, "h": 20, "cx": 450.0, "cy": 330.0}]
            # Tier 2 命中：软件窗口矩形区域 (100, 100)
            elif rx == 100 and ry == 100:
                return [{"text": "窗口按钮", "x": 120, "y": 120, "w": 50, "h": 20, "cx": 145.0, "cy": 130.0}]
        elif region is None:
            # Tier 3 兜底：全屏
            return [{"text": "全屏元素", "x": 800, "y": 600, "w": 80, "h": 25, "cx": 840.0, "cy": 612.5}]
        return []

    monkeypatch.setattr(vision_locator, "get_screen_elements", mock_get_screen_elements)

    # 1. 模拟鼠标位置在 (500, 400) -> 鼠标周边嗅探区域左上角为 400
    import pyautogui
    monkeypatch.setattr(pyautogui, "position", lambda: (500, 400))
    monkeypatch.setattr(pyautogui, "size", lambda: (1920, 1080))

    res_t1 = vision_locator.locate_text_on_screen("快速保存", use_hierarchical=True)
    assert res_t1 is not None
    assert res_t1.get("tier") == 1
    assert any(c is not None for c in calls)
    # Tier 1 命中后不应该调用全屏 (None)
    assert None not in calls

    # 2. 模拟 Tier 1 未命中，但 Tier 2（窗口范围）命中
    calls.clear()
    # 模拟 target_hwnd 存在
    import win32gui
    monkeypatch.setattr(win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(win32gui, "IsIconic", lambda h: False)
    monkeypatch.setattr(win32gui, "GetWindowRect", lambda h: (100, 100, 700, 600))
    res_t2 = vision_locator.locate_text_on_screen("窗口按钮", use_hierarchical=True, target_hwnd=12345)
    assert res_t2 is not None
    assert res_t2.get("tier") == 2
    # Tier 2 命中后不应该调用全屏 (None)
    assert None not in calls

    # 3. 模拟 Tier 1 & Tier 2 均未命中，降级到 Tier 3 全屏
    calls.clear()
    res_t3 = vision_locator.locate_text_on_screen("全屏元素", use_hierarchical=True)
    assert res_t3 is not None
    assert res_t3.get("tier") == 3
    assert None in calls


def test_get_screen_elements_region_isolation(monkeypatch):
    from uiu import vision_locator
    region_called = []
    full_called = []

    from uiu import screen_tools
    monkeypatch.setattr(screen_tools, "_ocr_region", lambda x, y, w, h: region_called.append((x, y, w, h)) or [])
    monkeypatch.setattr(screen_tools, "_ocr_full_screen", lambda: full_called.append(True) or [])

    # 当指定 region 时，严格只调用 _ocr_region，绝不执行全屏 OCR
    vision_locator.get_screen_elements(region=(100, 200, 300, 400))
    assert len(region_called) == 1
    assert region_called[0] == (100, 200, 300, 400)
    assert len(full_called) == 0

    # 当不指定 region 时，才调用 _ocr_full_screen
    vision_locator.get_screen_elements(region=None)
    assert len(full_called) == 1


# 10. 极速免思考复合动作流水线与毫秒级执行测试 (Requirement 10)
def test_gui_action_pipeline_subsecond_execution(monkeypatch):
    from uiu.fast_pipeline import gui_action_pipeline, check_chatgpt_quota
    import uiu.tools as tools

    # 1. 验证工具已注册
    assert "gui_action_pipeline" in tools.BUILTIN_TOOLS
    assert "check_chatgpt_quota" in tools.BUILTIN_TOOLS

    # 2. 模拟快速动作步骤执行 (3 步微动作)
    mock_steps = [
        {"action": "wait", "ms": 10},
        {"action": "wait", "ms": 15},
        {"action": "key", "key": "f12"},
    ]

    import uiu.gui_primitives as gp
    monkeypatch.setattr(gp, "press_key", lambda k: f"[ok] key {k}")

    res = gui_action_pipeline(mock_steps)
    assert "[流水线] 极速动作执行报告" in res
    assert "Step 1 [wait]" in res
    assert "Step 2 [wait]" in res
    assert "Step 3 [key]" in res
    assert "共 3 步" in res

    # 3. 容错测试：非法动作返回详细错误但流水线不崩溃
    bad_res = gui_action_pipeline([{"action": "non_existent_action"}])
    assert "未知动作: non_existent_action" in bad_res


