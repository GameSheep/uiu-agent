"""Tool-level guardrails end to end (no LLM / network needed)."""

import json


def _call(name, args, **kw):
    from uiu.tools import call_tool
    return call_tool(name, json.dumps(args), **kw)


def test_read_env_blocked(tmp_cwd):
    (tmp_cwd / "workspace").mkdir(exist_ok=True)
    (tmp_cwd / "workspace" / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    out = _call("read_file", {"path": "workspace/.env"})
    assert out.startswith("[error]"), out
    assert "sk-secret" not in out


def test_write_system_dir_blocked(tmp_cwd):
    import os
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    out = _call("write_file", {"path": f"{windir}/Temp/uiu_probe.txt", "content": "x"})
    assert out.startswith("[error]"), out


def test_shell_dangerous_blocked(tmp_cwd):
    out = _call("shell_exec", {"command": "shutdown /s /t 10"})
    assert out.startswith("[error]"), out


def test_shell_benign_ok(tmp_cwd):
    out = _call("shell_exec", {"command": "echo hello"})
    assert "hello" in out, out


def test_write_read_roundtrip(tmp_cwd):
    assert _call("write_file", {"path": "notes/hi.txt", "content": "hi there"}).startswith("[ok]")
    assert _call("read_file", {"path": "notes/hi.txt"}) == "hi there"


def test_open_url_scheme_blocked():
    from uiu.system_tools import open_url
    assert open_url("javascript:alert(1)").startswith("[error]")
    assert open_url("file:///etc/passwd").startswith("[error]")


def test_app_launch_injection_blocked():
    from uiu.window_manager import launch_application
    assert launch_application("notepad & calc").startswith("[error]")
    assert launch_application("").startswith("[error]")
    assert launch_application("javascript:alert(1)").startswith("[error]")


def test_desktop_dispatch_wiring():
    from uiu.desktop_tools import get_all_tool_schemas, dispatch_tool
    names = [d["function"]["name"] for d in get_all_tool_schemas()]
    for want in ("window_list", "window_focus", "app_launch", "screen_ocr_find",
                 "mouse_click_at", "text_paste", "keyboard_shortcut",
                 "mouse_scroll_at", "send_wechat"):
        assert want in names, want
    # 未知工具 + send_wechat 参数校验走统一入口（无 GUI 副作用）
    assert dispatch_tool("nope", {}).startswith("[error]")
    assert dispatch_tool("send_wechat", {"contact": "", "message": "x"}).startswith("[error]")


def test_hotkey_and_paste_guards():
    from uiu.gui_primitives import press_hotkey, press_key, paste_text
    assert press_hotkey([]).startswith("[error]")
    assert press_hotkey(["ctrl", "nosuchkey_xyz"]).startswith("[error]")
    assert press_hotkey(["a", "b", "c", "d", "e"]).startswith("[error]")
    assert press_key("nosuchkey_xyz").startswith("[error]")
    assert paste_text("x" * (100 * 1024 + 1)).startswith("[error]")


def test_delegate_validates_input(tmp_cwd):
    from uiu.agent_tools import delegate
    assert delegate("claude", "").startswith("[error]")
    assert delegate("nope", "do things").startswith("[error]")
    assert delegate("claude", "x" * 20001).startswith("[error]")
    import os
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    assert delegate("claude", "hi", cwd=windir).startswith("[error]")
