"""File operations tool — read, write, edit, glob, grep."""

import asyncio
from pathlib import Path

from .base import BaseTool, ToolResult


class FileOpsTool(BaseTool):
    name = "file_ops"
    description = "File operations — read, write, edit, glob, grep"

    def __init__(self, workspace: Path = None):
        self.workspace = Path(workspace).resolve() if workspace else Path.cwd().resolve()

    def _resolve_path(self, path: str) -> tuple:
        """Resolve path relative to workspace. Returns (resolved_path, error_msg)."""
        resolved = (self.workspace / path).resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            return None, f"Path '{path}' is outside workspace"
        return resolved, ""

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation", "")

        if operation == "read":
            return await self._read(kwargs.get("path", ""))
        elif operation == "write":
            return await self._write(kwargs.get("path", ""), kwargs.get("content", ""))
        elif operation == "edit":
            return await self._edit(
                kwargs.get("path", ""),
                kwargs.get("old_string", ""),
                kwargs.get("new_string", ""),
            )
        elif operation == "glob":
            return await self._glob(kwargs.get("pattern", ""))
        elif operation == "grep":
            return await self._grep(kwargs.get("pattern", ""), kwargs.get("path"))
        else:
            return ToolResult(success=False, error=f"Unknown operation: '{operation}'")

    async def _read(self, path: str) -> ToolResult:
        resolved, err = self._resolve_path(path)
        if err:
            return ToolResult(success=False, error=err)
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
            numbered = "\n".join(f"{i+1}: {line}" for i, line in enumerate(lines))
            return ToolResult(success=True, output=numbered)
        except FileNotFoundError:
            return ToolResult(success=False, error=f"File not found: {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _write(self, path: str, content: str) -> ToolResult:
        resolved, err = self._resolve_path(path)
        if err:
            return ToolResult(success=False, error=err)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Written: {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _edit(self, path: str, old_string: str, new_string: str) -> ToolResult:
        resolved, err = self._resolve_path(path)
        if err:
            return ToolResult(success=False, error=err)
        try:
            content = resolved.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ToolResult(success=False, error=f"File not found: {path}")
        if old_string not in content:
            return ToolResult(success=False, error=f"String not found in {path}: {old_string!r}")
        resolved.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return ToolResult(success=True, output=f"Edited: {path}")

    async def _glob(self, pattern: str) -> ToolResult:
        try:
            if "**" in pattern:
                matches = list(self.workspace.rglob(pattern.lstrip("**/") or pattern))
            else:
                matches = list(self.workspace.glob(pattern))
            names = [str(p.relative_to(self.workspace)) for p in sorted(matches)]
            return ToolResult(success=True, output="\n".join(names))
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _grep(self, pattern: str, path: str = None) -> ToolResult:
        if path:
            resolved, err = self._resolve_path(path)
            if err:
                return ToolResult(success=False, error=err)
            search_target = str(resolved)
        else:
            search_target = str(self.workspace)

        try:
            # Use create_subprocess_exec (not shell=True) to avoid injection
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", pattern, search_target,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace").strip()
            if proc.returncode not in (0, 1):  # grep returns 1 for no matches
                return ToolResult(success=False, error=stderr.decode())
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, error=str(e))
