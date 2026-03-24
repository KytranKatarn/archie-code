"""Shell operations tool — runs commands in a sandboxed workspace with denylist checking."""

import asyncio
from asyncio.subprocess import PIPE
from pathlib import Path

from archie_engine.tools.base import BaseTool, ToolResult


class ShellOpsTool(BaseTool):
    """Shell command execution with safety denylist."""

    name = "shell_ops"
    description = "Shell command execution with safety denylist"

    def __init__(self, workspace: Path = None, config=None):
        self.workspace = workspace or Path.cwd()
        self.config = config

    async def execute(self, **kwargs) -> ToolResult:
        command: str = kwargs.get("command", "")
        timeout: int = kwargs.get("timeout", 120)

        # Denylist check
        if self.config and hasattr(self.config, "shell_denylist"):
            for blocked in self.config.shell_denylist:
                if blocked in command:
                    return ToolResult(
                        success=False,
                        error=f"Command blocked by denylist: '{blocked}' is not permitted.",
                    )

        # Run the command
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=self.workspace,
                stdout=PIPE,
                stderr=PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return ToolResult(
                success=False,
                error=f"Command timeout after {timeout}s: {command}",
            )

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()

        if process.returncode != 0:
            return ToolResult(
                success=False,
                output=stdout_text,
                error=stderr_text or f"Command exited with code {process.returncode}",
            )

        return ToolResult(success=True, output=stdout_text, error=stderr_text)
