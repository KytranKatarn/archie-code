import pytest
from archie_engine.tools.shell_ops import ShellOpsTool
from archie_engine.config import EngineConfig


@pytest.fixture
def shell_tool(tmp_path):
    config = EngineConfig(data_dir=tmp_path)
    return ShellOpsTool(workspace=tmp_path, config=config)


@pytest.mark.asyncio
async def test_simple_command(shell_tool):
    result = await shell_tool.execute(command="echo hello")
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_cwd_is_workspace(shell_tool, tmp_path):
    result = await shell_tool.execute(command="pwd")
    assert result.success
    assert str(tmp_path) in result.output


@pytest.mark.asyncio
async def test_denylist_blocks_dangerous(shell_tool):
    result = await shell_tool.execute(command="rm -rf /")
    assert not result.success
    assert "blocked" in result.error.lower() or "denied" in result.error.lower()


@pytest.mark.asyncio
async def test_denylist_partial_match(shell_tool):
    result = await shell_tool.execute(command="rm -rf / --no-preserve-root")
    assert not result.success


@pytest.mark.asyncio
async def test_timeout(shell_tool):
    result = await shell_tool.execute(command="sleep 30", timeout=1)
    assert not result.success
    assert "timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_nonzero_exit(shell_tool):
    result = await shell_tool.execute(command="ls /nonexistent_dir_12345")
    assert not result.success


@pytest.mark.asyncio
async def test_stderr_in_error(shell_tool):
    result = await shell_tool.execute(command="ls /nonexistent_dir_12345")
    assert result.error  # stderr should be captured
