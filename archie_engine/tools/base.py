"""Base tool class and result type for all engine tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    output: str = ""
    error: str = ""
    metadata: dict = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base class for engine tools."""

    name: str = ""
    description: str = ""

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        ...

    def to_dict(self) -> dict:
        """Tool metadata for discovery."""
        return {"name": self.name, "description": self.description}
