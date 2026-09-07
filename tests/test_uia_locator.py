"""Tests for UIA locator: accessibility control search and listing."""

from unittest.mock import MagicMock, patch


class MockRect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class MockControl:
    def __init__(self, name, ctype, rect, auto_id="", children=None):
        self.Name = name
        self.ControlTypeName = ctype
        self.BoundingRectangle = rect
        self.AutomationId = auto_id
        self._children = children or []

    def GetChildren(self):
        return self._children


def test_find_uia_control_by_name_and_type():
    from uiu.uia_locator import find_uia_control

    btn_rect = MockRect(100, 200, 160, 240)
    btn = MockControl(name="编辑", ctype="ButtonControl", rect=btn_rect, auto_id="btn_edit")
    root = MockControl(name="MainWin", ctype="WindowControl", rect=MockRect(0, 0, 800, 600), children=[btn])

    with patch("uiautomation.GetRootControl", return_value=root), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        res = find_uia_control(name="编辑", control_type="Button")
        assert res is not None
        assert res["found"] is True
        assert res["cx"] == 130
        assert res["cy"] == 220
        assert res["automation_id"] == "btn_edit"


def test_find_uia_control_not_found():
    from uiu.uia_locator import find_uia_control

    root = MockControl(name="MainWin", ctype="WindowControl", rect=MockRect(0, 0, 800, 600), children=[])

    with patch("uiautomation.GetRootControl", return_value=root), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        res = find_uia_control(name="不存在的按钮", control_type="Button")
        assert res is None


def test_list_uia_controls():
    from uiu.uia_locator import list_uia_controls

    btn1 = MockControl(name="确定", ctype="ButtonControl", rect=MockRect(10, 10, 50, 40))
    edit1 = MockControl(name="输入框", ctype="EditControl", rect=MockRect(60, 10, 150, 40))
    root = MockControl(name="Main", ctype="WindowControl", rect=MockRect(0, 0, 500, 500), children=[btn1, edit1])

    with patch("uiautomation.GetRootControl", return_value=root), \
         patch("uiu.window_manager.ensure_default_desktop", return_value=True):
        ctrls = list_uia_controls()
        assert len(ctrls) == 2
        names = [c["name"] for c in ctrls]
        assert "确定" in names and "输入框" in names
