"""Registry regression tests — must import `uiu.tools` (the real entry), never bypass it.

These guard the P0 breakage: bare imports in desktop_tools/wechat_tools/vision_locator
and the missing WECHAT_TOOLS registry used to crash `import uiu.tools`, which every
runtime entrypoint (TUI / serve / agent) depends on.
"""

import json


def test_tools_module_imports():
    """The full registry must import without error (was ModuleNotFoundError/NameError)."""
    import uiu.tools  # noqa: F401


def test_registry_has_core_tools():
    import uiu.tools as t
    for name in ("shell_exec", "read_file", "write_file", "read_spreadsheet",
                 "send_wechat", "click_text", "screen_read_text", "type_text",
                 "window_list", "window_focus", "app_launch", "system_info",
                 "get_time", "check_network", "web_search", "memory_add",
                 "delegate_task", "skills_list", "skill_view", "look",
                 "speak", "proc_run", "press_key", "clipboard_get"):
        assert name in t.BUILTIN_TOOLS, f"missing builtin tool: {name}"


def test_registry_defs_have_unique_valid_names():
    import uiu.tools as t
    defs = t.tool_defs()
    names = [d["function"]["name"] for d in defs]
    assert len(names) == len(set(names)), "duplicate tool names in defs"
    assert all(isinstance(n, str) and n for n in names)


def test_every_registered_tool_has_callable_fn():
    import uiu.tools as t
    for name, entry in t.BUILTIN_TOOLS.items():
        assert callable(entry["fn"]), f"tool {name} fn not callable"
        assert entry["def"]["function"]["name"] == name, f"tool {name} def/name mismatch"


def test_call_tool_dispatch_and_error_paths():
    from uiu.tools import call_tool
    # benign builtin dispatches
    out = call_tool("read_file", json.dumps({"path": "nope_missing_xyz.txt"}))
    assert "not found" in out or out.startswith("[error]"), out
    # malformed JSON is caught, not raised
    out = call_tool("read_file", "{bad json")
    assert out.startswith("[error]"), out
    # unknown tool is caught
    out = call_tool("definitely_not_a_tool", "{}")
    assert out.startswith("[error]"), out


def test_desktop_and_ocr_modules_import():
    """The bridged desktop/wechat/vision modules must import as package members."""
    from uiu import desktop_tools, gui_primitives, vision_locator, window_manager
    from uiu import wechat_tools, screen_tools
    assert "send_wechat" in [d["function"]["name"] for d in desktop_tools.get_all_tool_schemas()]
    assert callable(screen_tools._ocr_full_screen)


def test_wechat_tools_registry_consistent():
    from uiu.wechat_tools import WECHAT_TOOLS, wechat_tool_defs
    assert "send_wechat" in WECHAT_TOOLS
    assert len(wechat_tool_defs()) == 1


def test_launch_application_blocks_shell_meta():
    """Guard against shell injection through app_launch (uses os.startfile, no shell)."""
    from uiu.window_manager import launch_application
    assert launch_application("notepad & calc").startswith("[error]")
    assert launch_application("").startswith("[error]")
    assert launch_application("javascript:alert(1)").startswith("[error]")
    assert launch_application("a|b").startswith("[error]")
