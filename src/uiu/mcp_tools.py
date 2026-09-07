"""MCP tools wrapper — exposes MCP server tools as uiu tools.

This module provides the bridge between MCP servers and uiu's tool system.
MCP tools are dynamically registered when MCP servers connect.
"""

from __future__ import annotations

from .mcp_client import mcp_call_tool_sync, mcp_tool_defs, get_mcp_manager


def mcp_call(arguments_json: str, tool_name: str = "") -> str:
    """Dispatch call to the appropriate MCP server tool.

    This is a generic handler — the actual tool_name is in the arguments
    or resolved by the tool dispatch system.
    """
    return mcp_call_tool_sync(tool_name, arguments_json)


# Tool definition for the MCP dispatcher
MCP_DISPATCHER_DEF = {
    "type": "function",
    "function": {
        "name": "mcp_call",
        "description": "调用 MCP (Model Context Protocol) 外部工具。由 MCP 服务器提供的扩展能力。",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "MCP 工具名（格式: mcp_服务器名_工具名）"},
                "arguments": {"type": "object", "description": "工具参数"},
            },
            "required": ["tool_name"],
        },
    },
}


MCP_TOOLS: dict[str, dict] = {}


def refresh_mcp_tools():
    """Refresh MCP tool definitions from connected servers."""
    global MCP_TOOLS
    defs = mcp_tool_defs()
    MCP_TOOLS = {}
    for d in defs:
        name = d["function"]["name"]
        MCP_TOOLS[name] = {
            "def": d,
            "fn": lambda args_json, n=name: mcp_call_tool_sync(n, args_json),
        }


def get_mcp_tools() -> dict[str, dict]:
    """Get all MCP tools (for tool registry)."""
    return MCP_TOOLS


def mcp_tool_defs_list() -> list[dict]:
    """Get MCP tool definitions (lazy-refresh once so connected servers show up)."""
    if not MCP_TOOLS:
        try:
            refresh_mcp_tools()
        except Exception:
            pass
    return [t["def"] for t in MCP_TOOLS.values()]


def try_connect_all(cfg) -> list[str]:
    """Connect to all configured MCP servers (best-effort, never raises).

    Call once at startup (TUI / gateway). After a successful connect the
    dynamic MCP tools appear in tool_defs() on the next refresh.

    Returns a list of human-readable status lines for the caller to print.
    """
    configs = getattr(cfg, "mcp_servers", None) or []
    if not configs:
        return []
    status: list[str] = []
    try:
        import asyncio
        from .mcp_client import get_mcp_manager
        manager = get_mcp_manager()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(manager.connect_all(configs))
        finally:
            loop.close()
        connected = list(manager.servers.keys())
        if connected:
            refresh_mcp_tools()
            n = len(get_mcp_tools())
            status.append(f"· MCP 已连接 {len(connected)} 个服务器，注入 {n} 个工具: {', '.join(connected)}")
        else:
            status.append("· MCP 未连接任何服务器（配置了但全部失败）")
    except Exception as e:
        status.append(f"· MCP 连接失败（已跳过）: {type(e).__name__}: {e}")
    return status
