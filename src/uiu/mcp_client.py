"""MCP (Model Context Protocol) client integration.

Connects uiu to external MCP servers, exposing their tools as native uiu tools.

Usage:
    1. Configure MCP servers in config.yaml:
       mcp_servers:
         - name: "filesystem"
           command: "npx"
           args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
         - name: "github"
           url: "https://api.github.com/mcp"
           headers:
             Authorization: "token ghp_xxx"

    2. Agent automatically connects and exposes MCP tools

Install:
    pip install "mcp[cli]"
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPServerConnection:
    """Manages a single MCP server connection."""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.session = None
        self._client = None
        self.tools: list[dict] = []

    async def connect(self):
        """Connect to the MCP server."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client

        transport = self.config.get("transport", "stdio")

        if transport == "stdio":
            # stdio transport: spawn a subprocess
            params = StdioServerParameters(
                command=self.config["command"],
                args=self.config.get("args", []),
                env=self.config.get("env"),
            )
            self._client = stdio_client(params)
            read, write = await self._client.__aenter__()
            self.session = ClientSession(read, write)
            await self.session.__aenter__()
            await self.session.initialize()

        elif transport in ("http", "streamable_http"):
            # HTTP transport: connect to remote server
            url = self.config["url"]
            headers = self.config.get("headers", {})
            self._client = streamablehttp_client(url, headers=headers)
            read, write, _ = await self._client.__aenter__()
            self.session = ClientSession(read, write)
            await self.session.__aenter__()
            await self.session.initialize()

        else:
            raise ValueError(f"Unknown transport: {transport}")

        # Fetch tools list
        tools_response = await self.session.list_tools()
        self.tools = []
        for tool in tools_response.tools:
            self.tools.append({
                "name": f"mcp_{self.name}_{tool.name}",
                "mcp_tool_name": tool.name,
                "description": tool.description or f"MCP tool: {tool.name}",
                "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            })

        logger.info(f"MCP server '{self.name}' connected: {len(self.tools)} tools")

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on this MCP server."""
        if self.session is None:
            return f"[error] MCP server '{self.name}' not connected"

        try:
            result = await self.session.call_tool(tool_name, arguments)
            # Extract text content from result
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                elif hasattr(content, "data"):
                    parts.append(f"[data] {content.data[:200]}")
            return "\n".join(parts) if parts else "(empty result)"
        except Exception as e:
            return f"[error] MCP call failed: {type(e).__name__}: {e}"

    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception:
                pass
            self.session = None
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self):
        self.servers: dict[str, MCPServerConnection] = {}

    async def connect_all(self, configs: list[dict]):
        """Connect to all configured MCP servers."""
        for config in configs:
            name = config.get("name", f"server_{len(self.servers)}")
            conn = MCPServerConnection(name, config)
            try:
                await conn.connect()
                self.servers[name] = conn
            except Exception as e:
                logger.warning(f"Failed to connect MCP server '{name}': {e}")

    async def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for name, conn in self.servers.items():
            try:
                await conn.disconnect()
            except Exception:
                pass
        self.servers.clear()

    def get_all_tools(self) -> list[dict]:
        """Get tool definitions from all connected MCP servers."""
        tools = []
        for conn in self.servers.values():
            for tool in conn.tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["input_schema"],
                    },
                    "_mcp_server": conn.name,
                    "_mcp_tool_name": tool["mcp_tool_name"],
                })
        return tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call an MCP tool by its full name (mcp_server_tool)."""
        # Find which server has this tool
        for conn in self.servers.values():
            for tool in conn.tools:
                if tool["name"] == tool_name:
                    return await conn.call_tool(tool["mcp_tool_name"], arguments)
        return f"[error] MCP tool not found: {tool_name}"

    @property
    def is_connected(self) -> bool:
        return len(self.servers) > 0


# Singleton manager
_manager = MCPManager()


def get_mcp_manager() -> MCPManager:
    """Get the global MCP manager instance."""
    return _manager


def mcp_tool_defs() -> list[dict]:
    """Get tool definitions for all connected MCP servers (without internal fields)."""
    tools = _manager.get_all_tools()
    # Remove internal fields before sending to LLM
    cleaned = []
    for t in tools:
        cleaned_t = {
            "type": t["type"],
            "function": {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "parameters": t["function"]["parameters"],
            },
        }
        cleaned.append(cleaned_t)
    return cleaned


async def mcp_call_tool(tool_name: str, arguments_json: str) -> str:
    """Call an MCP tool (async wrapper)."""
    try:
        args = json.loads(arguments_json) if isinstance(arguments_json, str) else arguments_json
        if not isinstance(args, dict):
            args = {}
        return await _manager.call_tool(tool_name, args)
    except json.JSONDecodeError as e:
        return f"[error] invalid JSON: {e}"
    except Exception as e:
        return f"[error] {type(e).__name__}: {e}"


def mcp_call_tool_sync(tool_name: str, arguments_json: str) -> str:
    """Call an MCP tool (sync wrapper for tool dispatch)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, create a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, mcp_call_tool(tool_name, arguments_json))
                return future.result(timeout=30)
        else:
            return loop.run_until_complete(mcp_call_tool(tool_name, arguments_json))
    except RuntimeError:
        # No event loop, create one
        return asyncio.run(mcp_call_tool(tool_name, arguments_json))
