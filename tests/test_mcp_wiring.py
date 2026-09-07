"""MCP wiring tests — connect is best-effort and must never break startup."""

import json


def test_try_connect_all_empty_cfg_returns_noop():
    from uiu.mcp_tools import try_connect_all

    class _Cfg:
        mcp_servers = []

    assert try_connect_all(_Cfg()) == []


def test_try_connect_all_bad_config_degrades_gracefully():
    """A config pointing at a nonexistent command must not raise at startup."""
    from uiu.mcp_tools import try_connect_all

    class _Cfg:
        mcp_servers = [{"name": "nope", "command": "definitely-not-a-real-cmd-xyz"}]

    out = try_connect_all(_Cfg())
    # returns status lines (never raises), and reports no successful connect
    assert isinstance(out, list)
    joined = "\n".join(out)
    assert "MCP" in joined


def test_mcp_call_unknown_tool_error():
    """mcp_call_tool_sync on a never-connected manager returns a clean error."""
    from uiu.mcp_client import mcp_call_tool_sync
    out = mcp_call_tool_sync("mcp_ghost_doit", json.dumps({}))
    assert out.startswith("[error]"), out
