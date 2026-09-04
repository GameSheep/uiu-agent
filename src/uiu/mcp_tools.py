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
