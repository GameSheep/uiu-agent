"""Unit tests for QuickMacro (F10/F12/F11) and action sequence pattern detector."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from uiu.pattern_detector import _step_to_token, detect_repeating_loop
from uiu.quick_macro import QuickMacroDaemon, QUICK_MACRO_NAME


# ==================== Pattern Detector Tests ====================

def test_step_to_token_fuzzy_coords():
    # Clicks within 15px bin should produce identical tokens
    s1 = {"t": "click", "x": 100, "y": 200, "button": "left"}
    s2 = {"t": "click", "x": 104, "y": 208, "button": "left"}
    assert _step_to_token(s1, coord_bin=15) == _step_to_token(s2, coord_bin=15)

    # Far clicks should produce different tokens
    s3 = {"t": "click", "x": 180, "y": 300, "button": "left"}
    assert _step_to_token(s1, coord_bin=15) != _step_to_token(s3, coord_bin=15)


def test_detect_repeating_loop_exact():
    loop = [
        {"t": "click", "x": 100, "y": 200, "button": "left"},
        {"t": "key", "key": "tab"},
        {"t": "click", "x": 300, "y": 400, "button": "left"},
    ]
    # 3 repetitions
    steps = loop * 3
    res = detect_repeating_loop(steps, min_repetitions=2)
    assert res["found"] is True
    assert res["period"] == 3
    assert res["repetitions"] == 3
    assert len(res["loop_steps"]) == 3
    assert res["loop_steps"][0]["t"] == "click"
    assert res["loop_steps"][1]["key"] == "tab"


def test_detect_repeating_loop_with_prefix_and_suffix_noise():
    prefix = [
        {"t": "click", "x": 10, "y": 10},
        {"t": "key", "key": "f5"},
    ]
    loop = [
        {"t": "click", "x": 100, "y": 100},
        {"t": "type", "text": "hello"},
        {"t": "key", "key": "enter"},
    ]
    suffix = [
        {"t": "click", "x": 999, "y": 999},
    ]

    steps = prefix + (loop * 3) + suffix
    res = detect_repeating_loop(steps, min_repetitions=2)
    assert res["found"] is True
    assert res["period"] == 3
    assert res["repetitions"] == 3
    assert res["start_index"] == 2
    assert res["end_index"] == 11
    assert len(res["loop_steps"]) == 3
    assert res["loop_steps"][1]["t"] == "type"


def test_detect_repeating_loop_no_pattern():
    steps = [
        {"t": "click", "x": 10, "y": 20},
        {"t": "key", "key": "a"},
        {"t": "scroll", "clicks": 5},
        {"t": "key", "key": "esc"},
    ]
    res = detect_repeating_loop(steps, min_repetitions=2)
    assert res["found"] is False
    assert res["period"] == 0


# ==================== QuickMacro State Machine Tests ====================

def test_quick_macro_state_transitions(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    events = []

    daemon = QuickMacroDaemon(workspace_root=ws, on_status_change=lambda st, msg: events.append((st, msg)))
    assert daemon.state == "IDLE"

    with patch("uiu.quick_macro.play_sound"):
        # 1. Press F10 -> starts recording
        daemon._handle_f10_toggle()
        assert daemon.state == "RECORDING"

        # Simulate actions
        daemon._raw_events.append({"t": "click", "x": 50, "y": 60, "button": "left", "clicks": 1, "delay_before": 0.1})
        daemon._raw_events.append({"t": "key", "key": "enter", "delay_before": 0.2})

        # 2. Press F10 again -> stops & saves
        daemon._handle_f10_toggle()
        assert daemon.state == "READY"
        assert daemon.macro_file.exists()

        # Check saved macro file
        with open(daemon.macro_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["name"] == QUICK_MACRO_NAME
        assert len(data["steps"]) == 2

        # 3. Press F11 in READY state -> abort / reset
        daemon._handle_f11_abort()
        assert daemon.state == "READY"


def test_quick_macro_f11_aborts_recording(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    daemon = QuickMacroDaemon(workspace_root=ws)
    with patch("uiu.quick_macro.play_sound"):
        daemon._handle_f10_toggle()
        assert daemon.state == "RECORDING"
        daemon._raw_events.append({"t": "click", "x": 1, "y": 2})

        # Press F11 while recording
        daemon._handle_f11_abort()
        assert daemon.state == "IDLE"
        assert len(daemon._raw_events) == 0


def test_quick_macro_replay_execution(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    daemon = QuickMacroDaemon(workspace_root=ws)
    with patch("uiu.quick_macro.play_sound"):
        # Record a step
        daemon._handle_f10_toggle()
        daemon._raw_events.append({"t": "key", "key": "tab", "delay_before": 0.0})
        daemon._handle_f10_toggle()
        assert daemon.state == "READY"

        with patch("uiu.quick_macro.play_steps", return_value=(1, "ok")) as mock_play:
            # Single replay (F12)
            daemon._handle_f12_replay(loop=False)
            if daemon._play_thread:
                daemon._play_thread.join(timeout=1.0)
            assert mock_play.call_count == 1
            assert daemon.state == "READY"

            # Loop replay (Ctrl+F12, 10 times)
            mock_play.reset_mock()
            daemon._handle_f12_replay(loop=True)
            if daemon._play_thread:
                daemon._play_thread.join(timeout=1.0)
            assert mock_play.call_count == 10
            assert daemon.state == "READY"


# ==================== Tool Integration Tests ====================

def test_tools_quick_macro_and_pattern(tmp_path, monkeypatch):
    from uiu.macros import quick_macro_listen, macro_detect_pattern, call_macro_tool, MACRO_TOOLS

    assert "quick_macro_listen" in MACRO_TOOLS
    assert "macro_detect_pattern" in MACRO_TOOLS

    # Stop daemon test
    out = quick_macro_listen("stop")
    assert "[ok]" in out

    # Start daemon test (mock pump to avoid real win32 hooks during headless pytest)
    with patch("uiu.quick_macro.QuickMacroDaemon.start"):
        out = quick_macro_listen("start")
        assert "[ok]" in out
        assert "F10" in out
        assert "F12" in out
        assert "F11" in out
    quick_macro_listen("stop")

    # Pattern detector tool test
    ws = tmp_path / "ws"
    ws.mkdir()
    macros_dir = ws / "macros"
    macros_dir.mkdir()
    test_macro_path = macros_dir / "test_flow.json"

    loop = [{"t": "click", "x": 100, "y": 100}, {"t": "key", "key": "tab"}]
    test_macro_path.write_text(json.dumps({
        "name": "test_flow",
        "description": "test",
        "steps": loop * 3
    }), encoding="utf-8")

    monkeypatch.setenv("UIU_WORKSPACE", str(ws))
    res = macro_detect_pattern("test_flow", save_as="extracted_loop")
    assert "[ok]" in res
    assert "提取后的循环宏" in res
    assert (macros_dir / "extracted_loop.json").exists()
