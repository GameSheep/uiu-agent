"""Tests for Trajectory-to-Macro Auto-Compiler."""

from uiu.trajectory_compiler import (
    ActionTrajectory,
    compile_trajectory_to_python,
    save_and_register_macro,
    run_compiled_macro,
    COMPILED_MACROS,
)


def test_compile_trajectory_to_python():
    traj = ActionTrajectory(
        name="test_login_flow",
        description="Auto login to service",
        target_app="TestApp",
        parameters=["username", "password"],
        steps=[
            {"action": "click", "x": 100, "y": 200},
            {"action": "type", "text": "username", "clear_before": True},
            {"action": "key", "key": "enter"},
        ],
    )
    code = compile_trajectory_to_python(traj)
    assert "def test_login_flow(username, password) -> str:" in code
    assert "Auto login to service" in code
    assert "mouse_click(100, 200, duration=0.0)" in code
    assert "paste_text(username, clear_before=True)" in code
    assert "press_key('enter')" in code


def test_save_and_run_compiled_macro(tmp_path):
    traj = ActionTrajectory(
        name="sample_sum_macro",
        description="A sample test macro",
        parameters=["item_val"],
        steps=[
            {"action": "type", "text": "item_val"},
        ],
    )
    fn_name, target_file = save_and_register_macro(traj, save_dir=tmp_path)
    assert target_file.exists()
    assert fn_name == "sample_sum_macro"
    assert "sample_sum_macro" in COMPILED_MACROS

    # Mock paste_text and run
    from unittest.mock import patch
    with patch("uiu.gui_primitives.paste_text", return_value="pasted_ok"), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        out = run_compiled_macro("sample_sum_macro", item_val="my_test_val")
        assert "sample_sum_macro" in out
        assert "原生宏执行成功" in out
        assert "my_test_val" in out
