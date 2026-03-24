"""Tests for GitOpsTool."""
import pytest
import subprocess
from archie_engine.tools.git_ops import GitOpsTool


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
    (tmp_path / "README.md").write_text("# Test")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    return tmp_path


@pytest.fixture
def git_tool(git_repo):
    return GitOpsTool(workspace=git_repo)


@pytest.mark.asyncio
async def test_status_clean(git_tool):
    result = await git_tool.execute(operation="status")
    assert result.success


@pytest.mark.asyncio
async def test_status_with_changes(git_tool, git_repo):
    (git_repo / "new.txt").write_text("changed")
    result = await git_tool.execute(operation="status")
    assert result.success
    assert "new.txt" in result.output


@pytest.mark.asyncio
async def test_diff(git_tool, git_repo):
    (git_repo / "README.md").write_text("# Modified")
    result = await git_tool.execute(operation="diff")
    assert result.success
    assert "Modified" in result.output


@pytest.mark.asyncio
async def test_log(git_tool):
    result = await git_tool.execute(operation="log", count=5)
    assert result.success
    assert "init" in result.output


@pytest.mark.asyncio
async def test_commit(git_tool, git_repo):
    (git_repo / "new.txt").write_text("content")
    subprocess.run(["git", "-C", str(git_repo), "add", "new.txt"], capture_output=True)
    result = await git_tool.execute(operation="commit", message="add new file")
    assert result.success


@pytest.mark.asyncio
async def test_branch_list(git_tool):
    result = await git_tool.execute(operation="branch")
    assert result.success


@pytest.mark.asyncio
async def test_not_a_repo(tmp_path):
    tool = GitOpsTool(workspace=tmp_path)
    result = await tool.execute(operation="status")
    assert not result.success
