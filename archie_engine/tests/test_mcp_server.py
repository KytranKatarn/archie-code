import pytest
import json
from archie_engine.claude.mcp_server import MCPToolServer


@pytest.fixture
def tool_defs():
    return [
        {"name": "file_read", "description": "Read a file", "parameters": {"path": {"type": "string"}}},
        {"name": "git_status", "description": "Git status", "parameters": {}},
        {"name": "shell_exec", "description": "Run shell command", "parameters": {"command": {"type": "string"}}},
    ]


@pytest.fixture
def server(tool_defs):
    return MCPToolServer(tools=tool_defs)


def test_handle_initialize(server):
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    assert result["result"]["capabilities"]["tools"] is not None
    assert result["result"]["serverInfo"]["name"] == "archie-engine"


def test_handle_tools_list(server):
    request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    tools = result["result"]["tools"]
    assert len(tools) == 3
    names = [t["name"] for t in tools]
    assert "file_read" in names


def test_handle_unknown_method(server):
    request = {"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}}
    response = server.handle_message(json.dumps(request))
    result = json.loads(response)
    assert "error" in result


def test_build_tool_definitions(server):
    defs = server.get_tool_definitions()
    assert len(defs) == 3
    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "inputSchema" in d


def test_handle_parse_error(server):
    response = server.handle_message("not json")
    result = json.loads(response)
    assert result["error"]["code"] == -32700


def test_handle_notification(server):
    request = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    response = server.handle_message(json.dumps(request))
    assert response == ""
