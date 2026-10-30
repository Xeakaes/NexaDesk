"""Adapt MCP tools into the NexaDesk Tool Registry.

Each discovered MCP tool becomes an MCPToolAdapter wrapping the shared
client call; the registry then exposes it through the normal schemas() /
PermissionPolicy path like any built-in tool. Error codes follow the
screen_control taxonomy where one exists (timeout, cancelled,
server_unreachable); protocol-level MCP failures land on mcp_error while
in-band tool failures (isError payload) land on tool_error.

MCP tool ``annotations`` (readOnlyHint/destructiveHint write hints) are
deliberately NOT derived into permission rules in M1: registered tool
names flow through the existing PermissionPolicy like built-in tools,
and hint-based level derivation is deferred to a later milestone.
"""

from __future__ import annotations

import json

from core.agent.cancellation import CancellationToken
from core.mcp.client import MCPClient, MCPClientError, MCPServerConfig
from core.tools.base import Tool, ToolResult
from core.tools.registry import ToolRegistry

_ERROR_CODES = {
    "cancelled": "cancelled",
    "timeout": "timeout",
    "server_crashed": "server_unreachable",
}


class MCPToolAdapter(Tool):
    def __init__(
        self,
        client: MCPClient,
        mcp_name: str,
        name: str,
        description: str,
        input_schema: dict,
    ) -> None:
        self.name = name
        self.description = description or f"MCP tool {mcp_name}"
        self.input_schema = input_schema or {}
        self._client = client
        self._mcp_name = mcp_name

    @staticmethod
    def _text_parts(payload: dict) -> list[str]:
        return [
            part.get("text", "")
            for part in payload.get("content") or []
            if isinstance(part, dict) and part.get("type") == "text"
        ]

    def execute(self, arguments: dict, cancel: CancellationToken) -> ToolResult:
        if cancel.cancelled:
            return ToolResult(
                ok=False, error="cancelled before call", error_code="cancelled"
            )
        try:
            payload = self._client.call_tool(self._mcp_name, arguments, cancel)
        except MCPClientError as exc:
            return ToolResult(
                ok=False,
                error=exc.message,
                error_code=_ERROR_CODES.get(exc.code, "mcp_error"),
            )
        text_parts = self._text_parts(payload)
        joined = "\n".join(text_parts)
        if payload.get("isError"):
            return ToolResult(ok=False, error=joined, error_code="tool_error")
        if not text_parts:
            return ToolResult(ok=True, data={})
        if len(text_parts) == 1:
            try:
                parsed = json.loads(text_parts[0])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                return ToolResult(ok=True, data=parsed)
        return ToolResult(ok=True, data={"result": joined})


def register_mcp_tools(
    registry: ToolRegistry, configs: list[MCPServerConfig]
) -> list[MCPClient]:
    """Start each configured server and register its discovered tools.

    Any failure closes every client started in this call before re-raising,
    so a partial registration never leaks a subprocess. Returns the started
    clients; the caller owns their close().
    """
    clients: list[MCPClient] = []
    try:
        for config in configs:
            client = MCPClient(config)
            clients.append(client)  # before start(): a failed handshake
            client.start()          # must still be closable below
            for tool in client.list_tools():
                mcp_name = tool["name"]
                registry.register(MCPToolAdapter(
                    client=client,
                    mcp_name=mcp_name,
                    name=f"{config.prefix}{mcp_name}",
                    description=tool.get("description") or "",
                    input_schema=dict(tool.get("inputSchema") or {}),
                ))
    except Exception:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass  # never mask the original registration failure
        raise
    return clients
