"""Tests for Multi-DPI Scaler & Coordinate Anti-Drift Engine."""

import pytest
from uiu.dpi_manager import (
    get_dpi_for_system,
    get_dpi_scale,
    list_monitors_geometry,
    get_virtual_screen_bounds,
    physical_to_logical,
    logical_to_physical,
    normalize_coordinates,
    denormalize_coordinates,
    calculate_safe_target,
    calibrate_screen_alignment,
)
from uiu.desktop_tools import dispatch_tool


def test_system_dpi_and_scale():
    dpi = get_dpi_for_system()
    assert dpi >= 96

    scale = get_dpi_scale()
    assert scale >= 1.0


def test_monitor_geometry_and_bounds():
    monitors = list_monitors_geometry()
    assert len(monitors) >= 1
    assert "rect" in monitors[0]
    assert "scale" in monitors[0]

    bounds = get_virtual_screen_bounds()
    assert len(bounds) == 4
    assert bounds[2] > 0 and bounds[3] > 0


def test_physical_logical_conversion():
    # Test with custom scaling factor of 1.5 (150% Windows scaling)
    phys_x, phys_y = 1500, 900
    log_x, log_y = physical_to_logical(phys_x, phys_y, custom_scale=1.5)
    assert log_x == 1000 and log_y == 600

    back_x, back_y = logical_to_physical(log_x, log_y, custom_scale=1.5)
    assert back_x == 1500 and back_y == 900

    # Test with 2.0 (200% 4K scaling)
    log_x2, log_y2 = physical_to_logical(2000, 1000, custom_scale=2.0)
    assert log_x2 == 1000 and log_y2 == 500


def test_coordinate_normalization_roundtrip():
    bounds = (0, 0, 1920, 1080)
    nx, ny = normalize_coordinates(960, 540, bounds=bounds)
    assert nx == 0.5 and ny == 0.5

    abs_x, abs_y = denormalize_coordinates(nx, ny, bounds=bounds)
    assert abs_x == 960 and abs_y == 540

    # Edge cases
    nx_edge, ny_edge = normalize_coordinates(0, 0, bounds=bounds)
    assert nx_edge == 0.0 and ny_edge == 0.0


def test_calculate_safe_target_strategies():
    # Box: left=100, top=200, width=200, height=50
    box_tuple = (100, 200, 200, 50)

    # 1. Standard center
    cx, cy = calculate_safe_target(box_tuple, strategy="center")
    assert cx == 200 and cy == 225

    # 2. Safe center (with margin)
    scx, scy = calculate_safe_target(box_tuple, strategy="safe_center", margin_ratio=0.15)
    assert scx == 200 and scy == 225

    # 3. Input field (left-biased safe typing area)
    ix, iy = calculate_safe_target(box_tuple, strategy="input_field")
    assert 130 <= ix <= 160
    assert iy == 225

    # 4. Right action (right-biased dropdown arrow)
    rx, ry = calculate_safe_target(box_tuple, strategy="right_action")
    assert 260 <= rx <= 280
    assert ry == 225

    # 5. Dict format with x1, y1, x2, y2
    dict_box = {"x1": 100, "y1": 200, "x2": 300, "y2": 250}
    dcx, dcy = calculate_safe_target(dict_box, strategy="center")
    assert dcx == 200 and dcy == 225


def test_screen_calibration_diagnostics():
    diag = calibrate_screen_alignment()
    assert diag["status"] == "calibrated"
    assert "system_scale" in diag
    assert "pyautogui_size" in diag
    assert "monitors_count" in diag
    assert diag["monitors_count"] >= 1


def test_gui_primitives_with_dpi_anti_drift(monkeypatch):
    import uiu.gui_primitives as gp

    clicks_recorded = []

    class MockPyAutoGUI:
        def moveTo(self, x, y, duration=0.0):
            pass
        def click(self, x, y, clicks=1, interval=0.02, button="left"):
            clicks_recorded.append((x, y, button))

    monkeypatch.setattr(gp, "_get_pyautogui", lambda: MockPyAutoGUI())
    monkeypatch.setattr("uiu.dpi_manager.get_virtual_screen_bounds", lambda: (0, 0, 1920, 1080))

    # Normalized click (0.5, 0.5) -> should denormalize to screen midpoint
    res1 = gp.mouse_click(0.5, 0.5)
    assert res1.startswith("[ok]")
    assert len(clicks_recorded) == 1
    assert clicks_recorded[0][0] > 0 and clicks_recorded[0][1] > 0

    # Physical click with is_physical=True
    res2 = gp.mouse_click(100, 100, is_physical=True)
    assert res2.startswith("[ok]")
    assert len(clicks_recorded) == 2


def test_desktop_tools_dpi_dispatch():
    # Test display_scaling_info tool
    res_info = dispatch_tool("display_scaling_info", {})
    assert "[ok] 显示器与 DPI 缩放诊断" in res_info
    assert "system_scale" in res_info

    # Test coordinate_anti_drift tool
    res_drift = dispatch_tool(
        "coordinate_anti_drift",
        {"box": [100, 200, 300, 40], "strategy": "input_field", "is_physical": False},
    )
    assert "[ok] 抗漂移安全坐标计算完成" in res_drift
    assert "target=" in res_drift
