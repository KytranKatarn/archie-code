"""Tool registry — register, discover, and execute tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseTool

from .base import ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s", tool.name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [t.to_dict() for t in self._tools.values()]

    async def execute(self, tool_name: str, **kwargs) -> ToolResult:
        # first param is tool_name (not 'name') so tools can take a 'name' kwarg
        # (e.g. git_ops branch create) without a "multiple values" collision.
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(success=False, error=f"Tool not found: {tool_name}")
        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            logger.error("Tool %s failed: %s", tool_name, e)
            return ToolResult(success=False, error=str(e))
