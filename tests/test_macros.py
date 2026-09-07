"""Macro record/play — synthesize logic, replay timing/abort, file roundtrip, CLI.

GUI 无关部分全部单测；真实钩子/鼠标键盘留给真机验证。
"""

import json
import threading
import time
from pathlib import Path


# ---------- recorder: pure synthesize ----------

def test_synthesize_click_and_wheel():
    from uiu.macro_recorder import _synthesize
    assert _synthesize({"type": "click", "x": 10, "y": 20, "button": "left"}) == \
        {"t": "click", "x": 10, "y": 20, "button": "left"}
    assert _synthesize({"type": "click", "x": 1, "y": 2, "button": "right"})["button"] == "right"
    w = _synthesize({"type": "wheel", "x": 5, "y": 6, "clicks": -3})
    assert w == {"t": "scroll", "clicks": -3, "x": 5, "y": 6}


def test_synthesize_control_keys():
    from uiu.macro_recorder import _synthesize
    # enter = VK 0x0D, tab = 0x09, F9 = 0x78, F5 = 0x74
    assert _synthesize({"type": "down", "vk": 0x0D}) == {"t": "key", "key": "enter"}
    assert _synthesize({"type": "down", "vk": 0x09}) == {"t": "key", "key": "tab"}
    assert _synthesize({"type": "down", "vk": 0x74}) == {"t": "key", "key": "f5"}


def test_synthesize_skips_printable_and_f9_stops():
    from uiu.macro_recorder import _synthesize
    assert _synthesize({"type": "down", "vk": 0x41}) is None  # 'A' — IME 不可靠不录
    assert _synthesize({"type": "down", "vk": 0x30}) is None  # '0'
    assert _synthesize({"type": "down", "vk": 0x78}) == {"stop": True}  # F9


def test_wheel_delta_to_clicks():
    from uiu.macro_recorder import _mouse_wheel_clicks
    assert _mouse_wheel_clicks(120 << 16) == 1
    assert _mouse_wheel_clicks(-120 << 16) == -1
    assert _mouse_wheel_clicks(240 << 16) == 2


# ---------- file roundtrip ----------

def test_save_load_roundtrip(tmp_path):
    from uiu.macro_recorder import save_macro, load_macro, macros_dir
    d = macros_dir(tmp_path / "ws")
    p = d / "m1.json"
    save_macro(p, "m1", "测试宏", [{"t": "click", "x": 1, "y": 2, "button": "left"}])
    data = load_macro(p)
    assert data["name"] == "m1" and data["description"] == "测试宏"
    assert data["steps"][0]["t"] == "click"


def test_load_invalid_json_raises(tmp_path):
    from uiu.macro_recorder import load_macro
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    import pytest
    with pytest.raises(Exception):
        load_macro(p)


def test_macro_name_sanitized(tmp_cwd):
    from uiu.macros import _valid_name
    assert _valid_name("my macro!") == "my_macro"
    assert _valid_name("  ") is None


# ---------- player ----------

def _steps():
    return [
        {"t": "click", "x": 10, "y": 20, "delay_before": 0.1},
        {"t": "key", "key": "enter", "delay_before": 0.2},
        {"t": "wait", "sec": 0.5, "delay_before": 0.0},
        {"t": "scroll", "clicks": -2, "delay_before": 0.3},
    ]


def test_play_empty_and_bad_speed():
    from uiu.macro_player import play_steps
    n, s = play_steps([])
    assert n == 0 and "空宏" in s
    n, s = play_steps(_steps(), speed=0)
    assert "speed" in s


def test_play_executes_all(monkeypatch):
    from uiu.macro_player import play_steps
    calls = []
    monkeypatch.setattr("uiu.macro_player.mouse_click", lambda **k: calls.append(("click", k)) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.press_key", lambda **k: calls.append(("key", k)) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.mouse_scroll", lambda **k: calls.append(("scroll", k)) or "[ok]")
    n, s = play_steps(_steps(), pause_between=0.0)
    assert n == 4 and "完成 4 步" in s
    assert calls[0][0] == "click" and calls[1][0] == "key" and calls[2][0] == "scroll"


def test_play_honors_range(monkeypatch):
    from uiu.macro_player import play_steps
    calls = []
    monkeypatch.setattr("uiu.macro_player.mouse_click", lambda **k: calls.append(1) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.press_key", lambda **k: calls.append(1) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.mouse_scroll", lambda **k: calls.append(1) or "[ok]")
    n, _ = play_steps(_steps(), pause_between=0.0, start=2, end=3)
    assert n == 2 and len(calls) == 1  # 第2步 key 调 GUI；第3步 wait 不调


def test_play_stops_on_stop_flag(monkeypatch):
    from uiu.macro_player import play_steps
    calls = []
    monkeypatch.setattr("uiu.macro_player.mouse_click", lambda **k: calls.append(1) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.press_key", lambda **k: calls.append(1) or "[ok]")
    monkeypatch.setattr("uiu.macro_player.mouse_scroll", lambda **k: calls.append(1) or "[ok]")
    flag = threading.Event()

    def _set_after_first(**k):
        calls.append(1)
        flag.set()  # 第一步后置位
        return "[ok]"

    monkeypatch.setattr("uiu.macro_player.mouse_click", _set_after_first)
    n, s = play_steps(_steps(), pause_between=0.0, stop_flag=flag)
    assert n == 1 and "中止" in s


def test_play_stops_on_step_error(monkeypatch):
    from uiu.macro_player import play_steps
    monkeypatch.setattr("uiu.macro_player.mouse_click", lambda **k: "[error] 点击失败")
    n, s = play_steps(_steps(), pause_between=0.0)
    assert n == 0 and "[error]" in s


def test_play_bad_step_type():
    from uiu.macro_player import play_steps
    n, s = play_steps([{"t": "fly", "delay_before": 0}], pause_between=0)
    assert "未知步骤类型" in s


# ---------- macro tools ----------

def test_macro_tools_registered():
    from uiu.tools import BUILTIN_TOOLS, tool_groups
    for want in ("macro_record", "macro_play", "macro_list", "macro_remove"):
        assert want in BUILTIN_TOOLS
    grouped = [n for _, names in tool_groups() for n in names]
    assert set(grouped) == set(BUILTIN_TOOLS)


def test_macro_list_and_remove(tmp_cwd):
    from uiu.macros import macro_list, macro_remove
    from uiu.macro_recorder import macros_dir, save_macro
    ws = tmp_cwd / "workspace"
    save_macro(macros_dir(ws) / "a.json", "a", "宏A", [{"t": "key", "key": "enter"}])
    out = macro_list()
    assert "a" in out and "1 步" in out
    assert macro_remove("a").startswith("[ok]")
    assert macro_list().startswith("(无宏")


def test_macro_play_tool_roundtrip(tmp_cwd, monkeypatch):
    """agent 生成宏文件 → macro_play 工具能读并执行（AI 写脚本闭环）。"""
    from uiu.macros import macro_play
    from uiu.macro_recorder import macros_dir
    ws = tmp_cwd / "workspace"
    steps = [
        {"t": "click", "x": 100, "y": 200, "delay_before": 0.1},
        {"t": "type", "text": "hello", "delay_before": 0.1},
        {"t": "key", "key": "enter", "delay_before": 0.2},
    ]
    (macros_dir(ws) / "ai_gen.json").write_text(
        json.dumps({"name": "ai_gen", "description": "AI 生成的宏", "steps": steps}, ensure_ascii=False),
        encoding="utf-8")
    calls = []
    monkeypatch.setattr("uiu.macro_player.mouse_click", lambda **k: calls.append("click") or "[ok]")
    monkeypatch.setattr("uiu.macro_player.paste_text", lambda **k: calls.append("type") or "[ok]")
    monkeypatch.setattr("uiu.macro_player.press_key", lambda **k: calls.append("key") or "[ok]")
    out = macro_play("ai_gen")
    assert "3 步" in out and calls == ["click", "type", "key"]


def test_macro_play_missing(tmp_cwd):
    from uiu.macros import macro_play
    out = macro_play("nope")
    assert out.startswith("[error]") and "宏不存在" in out


# ---------- CLI ----------

def test_cli_macro_list_and_remove(tmp_cwd, capsys):
    import argparse
    from uiu.commands import cmd_macro
    from uiu.macro_recorder import macros_dir, save_macro
    ws = tmp_cwd / "workspace"
    save_macro(macros_dir(ws) / "x.json", "x", "desc", [{"t": "key", "key": "tab"}])
    assert cmd_macro(argparse.Namespace(workspace=str(ws), action="list")) == 0
    assert "x" in capsys.readouterr().out
    ns = argparse.Namespace(workspace=str(ws), action="remove", name="x")
    assert cmd_macro(ns) == 0
    assert cmd_macro(argparse.Namespace(workspace=str(ws), action="remove", name="x")) == 2
