"""ShellOpsTool has two trust levels since #6657.

The tests below marked ``trusted=True`` exercise the ORIGINAL contract, which the
autonomous build loop still uses (shell, pipes, denylist). The default (untrusted)
path is an allowlist — see tests/test_shell_policy.py for the policy itself; the
last two tests here pin that the DEFAULT is the untrusted path.
"""

import pytest
from archie_engine.tools.shell_ops import ShellOpsTool
from archie_engine.config import EngineConfig


@pytest.fixture
def shell_tool(tmp_path):
    config = EngineConfig(data_dir=tmp_path)
    return ShellOpsTool(workspace=tmp_path, config=config)


@pytest.mark.asyncio
async def test_simple_command(shell_tool):
    result = await shell_tool.execute(command="echo hello", trusted=True)
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_cwd_is_workspace(shell_tool, tmp_path):
    result = await shell_tool.execute(command="pwd", trusted=True)
    assert result.success
    assert str(tmp_path) in result.output


@pytest.mark.asyncio
async def test_denylist_blocks_dangerous(shell_tool):
    result = await shell_tool.execute(command="rm -rf /", trusted=True)
    assert not result.success
    assert "blocked" in result.error.lower() or "denied" in result.error.lower()


@pytest.mark.asyncio
async def test_denylist_partial_match(shell_tool):
    result = await shell_tool.execute(command="rm -rf / --no-preserve-root", trusted=True)
    assert not result.success


@pytest.mark.asyncio
async def test_timeout(shell_tool):
    result = await shell_tool.execute(command="sleep 30", timeout=1, trusted=True)
    assert not result.success
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_nonzero_exit(shell_tool):
    result = await shell_tool.execute(command="ls /nonexistent_dir_12345", trusted=True)
    assert not result.success


@pytest.mark.asyncio
async def test_stderr_in_error(shell_tool):
    result = await shell_tool.execute(command="ls /nonexistent_dir_12345", trusted=True)
    assert result.error  # stderr should be captured


@pytest.mark.asyncio
async def test_default_is_the_untrusted_allowlist(shell_tool):
    """A ws client typing `run echo hello` gets the allowlist, not a shell."""
    result = await shell_tool.execute(command="echo hello")
    assert not result.success
    assert result.error.startswith("refused by shell policy")


@pytest.mark.asyncio
async def test_untrusted_allowlisted_command_runs(shell_tool, tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    result = await shell_tool.execute(command="ls")
    assert result.success and "marker.txt" in result.output
