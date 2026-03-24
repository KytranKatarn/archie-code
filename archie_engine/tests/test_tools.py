import pytest
from archie_engine.tools.base import BaseTool, ToolResult
from archie_engine.tools import ToolRegistry


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes input back"

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=kwargs.get("text", ""))


@pytest.mark.asyncio
async def test_registry_register_and_get():
    registry = ToolRegistry()
    registry.register(EchoTool())
    tool = registry.get("echo")
    assert tool is not None
    assert tool.name == "echo"


@pytest.mark.asyncio
async def test_registry_execute():
    registry = ToolRegistry()
    registry.register(EchoTool())
    result = await registry.execute("echo", text="hello")
    assert result.success is True
    assert result.output == "hello"


def test_registry_list_tools():
    registry = ToolRegistry()
    registry.register(EchoTool())
    tools = registry.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "echo"


@pytest.mark.asyncio
async def test_registry_unknown_tool():
    registry = ToolRegistry()
    result = await registry.execute("nonexistent")
    assert result.success is False
    assert "not found" in result.error.lower()
