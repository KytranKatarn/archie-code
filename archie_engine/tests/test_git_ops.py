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


# --- per-build worktree isolation (#4253) ---------------------------------------


@pytest.mark.asyncio
async def test_worktree_add_off_ref_and_remove(git_tool, tmp_path):
    """worktree add off a base ref creates a pristine tree; remove deletes it."""
    wt = tmp_path / "wt"
    add = await git_tool.execute(operation="worktree", action="add",
                                 path=str(wt), base="HEAD")
    assert add.success, add.error
    assert (wt / "README.md").exists()
    rm = await git_tool.execute(operation="worktree", action="remove", path=str(wt))
    assert rm.success, rm.error
    assert not wt.exists()


@pytest.mark.asyncio
async def test_worktree_remove_needs_force_when_dirty(git_tool, tmp_path):
    """A FAILED build leaves edits in its worktree — removal needs force=True."""
    wt = tmp_path / "wt2"
    add = await git_tool.execute(operation="worktree", action="add",
                                 path=str(wt), base="HEAD")
    assert add.success, add.error
    (wt / "README.md").write_text("dirty edit from a failed build")
    no_force = await git_tool.execute(operation="worktree", action="remove", path=str(wt))
    assert not no_force.success  # git refuses to drop a dirty worktree
    forced = await git_tool.execute(operation="worktree", action="remove",
                                    path=str(wt), force=True)
    assert forced.success, forced.error
    assert not wt.exists()


@pytest.mark.asyncio
async def test_branch_delete(git_tool, git_repo):
    await git_tool.execute(operation="branch", action="create", name="feature/x")
    subprocess.run(["git", "-C", str(git_repo), "checkout", "-"], capture_output=True)
    res = await git_tool.execute(operation="branch", action="delete", name="feature/x")
    assert res.success, res.error


@pytest.mark.asyncio
async def test_branch_delete_refuses_protected(git_tool):
    res = await git_tool.execute(operation="branch", action="delete", name="main")
    assert not res.success
    assert "protected" in res.error.lower()


@pytest.mark.asyncio
async def test_fetch(git_tool, git_repo, tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "remote", "add", "origin", str(origin)], capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "push", "origin", "HEAD"], capture_output=True)
    res = await git_tool.execute(operation="fetch", remote="origin")
    assert res.success, res.error
