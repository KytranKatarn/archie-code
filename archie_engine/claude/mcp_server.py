"""MCP server — exposes engine tools to Claude CLI via JSON-RPC."""

import json
import logging

logger = logging.getLogger(__name__)

MCP_VERSION = "2024-11-05"


class MCPToolServer:
    def __init__(self, tools: list[dict]):
        self._tools = tools
        self._tool_handler = None

    def set_tool_handler(self, handler):
        self._tool_handler = handler

    def get_tool_definitions(self) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "inputSchema": {"type": "object", "properties": t.get("parameters", {})},
            }
            for t in self._tools
        ]

    def handle_message(self, raw: str) -> str:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return self._error_response(None, -32700, "Parse error")

        msg_id = msg.get("id")
        method = msg.get("method", "")

        if method == "initialize":
            return self._success_response(msg_id, {
                "protocolVersion": MCP_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "archie-engine", "version": "0.1.0"},
            })

        if method == "tools/list":
            return self._success_response(msg_id, {"tools": self.get_tool_definitions()})

        if method == "notifications/initialized":
            return ""

        return self._error_response(msg_id, -32601, f"Method not found: {method}")

    def _success_response(self, msg_id, result: dict) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result})

    def _error_response(self, msg_id, code: int, message: str) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})
