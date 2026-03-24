"""Git operations tool for the ARCHIE Engine."""

import asyncio
from pathlib import Path

from archie_engine.tools.base import BaseTool, ToolResult


class GitOpsTool(BaseTool):
    """Git operations — status, diff, log, commit, branch."""

    name = "git_ops"
    description = "Git operations — status, diff, log, commit, branch"

    def __init__(self, workspace: Path = None):
        self.workspace = workspace or Path.cwd()

    async def _run_git(self, *args) -> tuple[str, str, int]:
        """Run git command in workspace, returns (stdout, stderr, returncode)."""
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(self.workspace), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode(), stderr.decode(), proc.returncode

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation", "status")

        if operation == "status":
            return await self._status()
        elif operation == "diff":
            return await self._diff(staged=kwargs.get("staged", False))
        elif operation == "log":
            return await self._log(count=kwargs.get("count", 10))
        elif operation == "commit":
            message = kwargs.get("message")
            if not message:
                return ToolResult(success=False, error="commit requires a 'message' kwarg")
            return await self._commit(message)
        elif operation == "branch":
            action = kwargs.get("action", "list")
            name = kwargs.get("name")
            return await self._branch(action=action, name=name)
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    async def _status(self) -> ToolResult:
        stdout, stderr, rc = await self._run_git("status", "--porcelain")
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        stdout2, _, _ = await self._run_git("status", "--short")
        output = stdout2 if stdout2.strip() else "(clean)"
        return ToolResult(success=True, output=output)

    async def _diff(self, staged: bool = False) -> ToolResult:
        args = ["diff", "--staged"] if staged else ["diff"]
        stdout, stderr, rc = await self._run_git(*args)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout)

    async def _log(self, count: int = 10) -> ToolResult:
        stdout, stderr, rc = await self._run_git("log", "--oneline", f"-{count}")
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout)

    async def _commit(self, message: str) -> ToolResult:
        stdout, stderr, rc = await self._run_git("commit", "-m", message)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout.strip())

    async def _branch(self, action: str = "list", name: str = None) -> ToolResult:
        if action == "list" or name is None:
            stdout, stderr, rc = await self._run_git("branch")
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=stdout)
        elif action == "create":
            stdout, stderr, rc = await self._run_git("checkout", "-b", name)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=stdout.strip())
        elif action == "switch":
            stdout, stderr, rc = await self._run_git("checkout", name)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=stdout.strip())
        else:
            return ToolResult(success=False, error=f"Unknown branch action: {action}")
