import pytest
from pathlib import Path
from archie_engine.tools.file_ops import FileOpsTool


@pytest.fixture
def file_tool(tmp_path):
    return FileOpsTool(workspace=tmp_path)


@pytest.mark.asyncio
async def test_read_file(file_tool, tmp_path):
    (tmp_path / "test.txt").write_text("hello world")
    result = await file_tool.execute(operation="read", path="test.txt")
    assert result.success
    assert "hello world" in result.output


@pytest.mark.asyncio
async def test_write_file(file_tool, tmp_path):
    result = await file_tool.execute(operation="write", path="new.txt", content="created")
    assert result.success
    assert (tmp_path / "new.txt").read_text() == "created"


@pytest.mark.asyncio
async def test_edit_file(file_tool, tmp_path):
    (tmp_path / "edit.txt").write_text("old value")
    result = await file_tool.execute(
        operation="edit", path="edit.txt", old_string="old value", new_string="new value"
    )
    assert result.success
    assert (tmp_path / "edit.txt").read_text() == "new value"


@pytest.mark.asyncio
async def test_glob(file_tool, tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = await file_tool.execute(operation="glob", pattern="*.py")
    assert result.success
    assert "a.py" in result.output
    assert "b.py" in result.output
    assert "c.txt" not in result.output


@pytest.mark.asyncio
async def test_grep(file_tool, tmp_path):
    (tmp_path / "search.py").write_text("def hello():\n    return 'world'\n")
    result = await file_tool.execute(operation="grep", pattern="hello", path="search.py")
    assert result.success
    assert "def hello" in result.output


@pytest.mark.asyncio
async def test_read_outside_workspace_blocked(file_tool):
    result = await file_tool.execute(operation="read", path="/etc/passwd")
    assert not result.success
    assert "outside workspace" in result.error.lower()


@pytest.mark.asyncio
async def test_write_outside_workspace_blocked(file_tool):
    result = await file_tool.execute(operation="write", path="/tmp/evil.txt", content="bad")
    assert not result.success


@pytest.mark.asyncio
async def test_read_nonexistent(file_tool):
    result = await file_tool.execute(operation="read", path="nope.txt")
    assert not result.success


@pytest.mark.asyncio
async def test_edit_no_match(file_tool, tmp_path):
    (tmp_path / "x.txt").write_text("abc")
    result = await file_tool.execute(
        operation="edit", path="x.txt", old_string="zzz", new_string="yyy"
    )
    assert not result.success
