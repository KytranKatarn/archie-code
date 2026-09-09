"""Shell operations tool — TWO trust levels (#6657).

``trusted=True`` (the autonomous build loop only — ``build_loop.py``): the original
behaviour. The command string comes from engine config / code, needs pipes
(``git show HEAD:p | wc -l``, ``… | xargs -r python -m py_compile``), and runs through
``create_subprocess_shell`` after the substring denylist.

``trusted=False`` (the DEFAULT — the ws ``message`` path ``"run <cmd>"`` via
``router.py`` and the MCP ``shell_exec`` tool): the command comes from a remote
client. A denylist cannot secure that (``cat /workspace-platform/.env`` was never on
it), so the untrusted path is an ALLOWLIST enforced by :func:`validate_untrusted`:

  * no shell metacharacters at all — the string is ``shlex.split`` and executed with
    ``create_subprocess_exec`` (no shell);
  * ``argv[0]`` must be one of ``pytest`` · ``python``/``python3`` (only ``-m pytest`` /
    ``-m py_compile``) · ``git`` (read-only subcommands, fixed flag set) · ``ls``;
  * any absolute path argument must resolve under an allowed workspace root;
  * the child's environment is scrubbed of ``*_TOKEN`` / ``*_KEY`` / ``*_SECRET`` /
    ``*PASSWORD`` variables — ``pytest`` executes workspace ``conftest.py`` code.

Owner decision 2026-09-09: strict allowlist (keep the cockpit's "run pytest"
convenience) rather than removing shell from the ws surface.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from asyncio.subprocess import PIPE
from pathlib import Path

from archie_engine.tools.base import BaseTool, ToolResult


class ShellPolicyError(ValueError):
    """The untrusted command is outside the allowlist."""


_METACHARS = set("|;&$<>(){}`\n\r")
_GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
_GIT_FLAGS = {
    "--stat",
    "--name-only",
    "--name-status",
    "--oneline",
    "--cached",
    "--short",
    "--list",
    "-a",
    "-p",
    "--abbrev-ref",
    "--show-toplevel",
    "--no-color",
}
_GIT_COUNT_FLAG = re.compile(r"^-(n)?\d{1,4}$")  # -5 / -n5
_LS_FLAGS = {"-l", "-a", "-la", "-al", "-lah", "-1", "-h"}
_PYTHON_MODULES = {"pytest", "py_compile"}
_SCRUB_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "PASSWORD", "_PASS")


def scrubbed_env() -> dict[str, str]:
    """Child environment without credentials (suffix match, case-insensitive)."""
    out: dict[str, str] = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if any(ku.endswith(sfx) for sfx in _SCRUB_SUFFIXES):
            continue
        out[k] = v
    return out


def _path_under_roots(arg: str, roots: list[Path]) -> bool:
    try:
        rp = Path(arg).resolve()
    except (OSError, RuntimeError):
        return False
    return any(rp == r or r in rp.parents for r in roots)


def validate_untrusted(command: str, roots: list[Path]) -> list[str]:
    """Return argv for an allowlisted command, or raise :class:`ShellPolicyError`."""
    if not command or not command.strip():
        raise ShellPolicyError("empty command")
    bad = sorted({c for c in command if c in _METACHARS})
    if bad:
        raise ShellPolicyError(f"shell metacharacters are not allowed: {' '.join(repr(c) for c in bad)}")
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise ShellPolicyError(f"cannot parse command: {e}") from e
    if not argv:
        raise ShellPolicyError("empty command")
    prog = argv[0]
    if "/" in prog:
        raise ShellPolicyError("program must be a bare name from the allowlist, not a path")
    args = argv[1:]

    if prog == "pytest":
        pass
    elif prog in ("python", "python3"):
        if len(args) < 2 or args[0] != "-m" or args[1] not in _PYTHON_MODULES:
            raise ShellPolicyError("python is allowed only as `python -m pytest …` or `python -m py_compile …`")
    elif prog == "git":
        if not args or args[0] not in _GIT_SUBCOMMANDS:
            raise ShellPolicyError(f"git subcommand not allowed (allowed: {', '.join(sorted(_GIT_SUBCOMMANDS))})")
        for a in args[1:]:
            if a.startswith("-") and a not in _GIT_FLAGS and not _GIT_COUNT_FLAG.match(a) and a != "--":
                raise ShellPolicyError(f"git flag not allowed: {a}")
    elif prog == "ls":
        for a in args:
            if a.startswith("-") and a not in _LS_FLAGS:
                raise ShellPolicyError(f"ls flag not allowed: {a}")
    else:
        raise ShellPolicyError(f"program not allowed: {prog}")

    for a in args:
        if a.startswith("-"):
            continue
        # Absolute paths and parent-walks must stay inside an allowed workspace.
        if a.startswith("/") or ".." in Path(a).parts:
            if not roots or not _path_under_roots(a if a.startswith("/") else str(roots[0] / a), roots):
                raise ShellPolicyError(f"path outside allowed workspaces: {a}")
    return argv


class ShellOpsTool(BaseTool):
    """Shell command execution: allowlist for clients, denylist+shell for the build loop."""

    name = "shell_ops"
    description = "Shell command execution (untrusted: allowlist; trusted build loop: denylist)"

    def __init__(self, workspace: Path = None, config=None):
        self.workspace = workspace or Path.cwd()
        self.config = config

    def _roots(self) -> list[Path]:
        try:
            from archie_engine.workspace_ops import allowed_roots

            roots = allowed_roots()
        except Exception:
            roots = []
        ws = Path(self.workspace).resolve()
        if ws not in roots:
            roots.append(ws)
        return roots

    async def execute(self, **kwargs) -> ToolResult:
        command: str = kwargs.get("command", "")
        timeout: int = kwargs.get("timeout", 120)
        trusted: bool = bool(kwargs.get("trusted", False))

        if trusted:
            return await self._execute_trusted(command, timeout)

        try:
            argv = validate_untrusted(command, self._roots())
        except ShellPolicyError as e:
            return ToolResult(success=False, error=f"refused by shell policy: {e}")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self.workspace,
                env=scrubbed_env(),
                stdout=PIPE,
                stderr=PIPE,
            )
        except FileNotFoundError:
            return ToolResult(success=False, error=f"program not found: {argv[0]}")
        return await self._collect(process, command, timeout)

    async def _execute_trusted(self, command: str, timeout: int) -> ToolResult:
        # Denylist check (config-driven substrings) — the pre-#6657 behaviour, kept
        # ONLY for commands the engine itself composes (build/test loop).
        if self.config and hasattr(self.config, "shell_denylist"):
            for blocked in self.config.shell_denylist:
                if blocked in command:
                    return ToolResult(
                        success=False,
                        error=f"Command blocked by denylist: '{blocked}' is not permitted.",
                    )
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=self.workspace,
            stdout=PIPE,
            stderr=PIPE,
        )
        return await self._collect(process, command, timeout)

    @staticmethod
    async def _collect(process, command: str, timeout: int) -> ToolResult:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return ToolResult(success=False, error=f"Command timeout after {timeout}s: {command}")

        stdout_text = stdout.decode(errors="replace").strip()
        stderr_text = stderr.decode(errors="replace").strip()
        if process.returncode != 0:
            return ToolResult(
                success=False,
                output=stdout_text,
                error=stderr_text or f"Command exited with code {process.returncode}",
            )
        return ToolResult(success=True, output=stdout_text, error=stderr_text)
