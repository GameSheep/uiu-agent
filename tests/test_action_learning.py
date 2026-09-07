"""Tests for action learning & decomposition into skills and MEMORY.md."""

import json
from pathlib import Path


def _ws_root(tmp_cwd) -> Path:
    p = tmp_cwd / "workspace"
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_record_verified_action_creates_skill_and_memory(tmp_cwd):
    from uiu.learning import record_verified_action
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")

    steps = [
        "ShowWindow(hwnd, SW_RESTORE) 唤醒最小化窗口",
        "鼠标移至卡片行 (win_left+500, card_cy) 触发悬浮按钮",
        "点击蓝色按钮右侧 +22px 处铅笔编辑图标",
        "备注输入框清空并剪贴板粘贴新内容",
        "点击保存",
    ]
    res = record_verified_action(
        action_name="test_cc_switch_action",
        target_app="CC Switch",
        steps=steps,
        verification="SQLite 校验 providers.notes 字段",
        notes="注意中文输入法会吃字符，必须用剪贴板粘贴",
    )
    assert "[ok]" in res

    # 1. Verify SKILL.md
    skill_file = root / "skills" / "test_cc_switch_action" / "SKILL.md"
    assert skill_file.exists()
    content = skill_file.read_text(encoding="utf-8")
    assert "name: test_cc_switch_action" in content
    assert "CC Switch" in content
    assert "ShowWindow(hwnd, SW_RESTORE)" in content
    assert "SQLite 校验" in content

    # 2. Verify MEMORY.md
    mem_text = (root / "MEMORY.md").read_text(encoding="utf-8")
    assert "[CC Switch] 已验证操作 'test_cc_switch_action'" in mem_text


def test_call_learning_tool_record_verified_action(tmp_cwd):
    from uiu.learning import call_learning_tool
    root = _ws_root(tmp_cwd)
    (root / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")

    payload = {
        "action_name": "auto_save_step",
        "target_app": "Notepad",
        "steps": ["Ctrl+S", "回车确认"],
        "verification": "文件内容已更新",
    }
    res = call_learning_tool("record_verified_action", json.dumps(payload))
    assert "[ok]" in res

    skill_file = root / "skills" / "auto_save_step" / "SKILL.md"
    assert skill_file.exists()
