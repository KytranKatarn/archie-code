import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from archie_engine.skills import SkillRegistry
from archie_engine.skills.executor import SkillExecutor


@pytest.fixture
def skill_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "commit.md").write_text("---\nname: commit\ndescription: Create commit\narguments:\n  - name: message\n    required: false\n---\nCommit stuff.")
    (d / "review.md").write_text("---\nname: review\ndescription: Review code\n---\nReview stuff.")
    return d


@pytest.fixture
def mock_executor():
    executor = AsyncMock(spec=SkillExecutor)
    executor.execute = AsyncMock(return_value={"success": True, "response": "Done!", "skill": "commit"})
    return executor


@pytest.fixture
def registry(skill_dir, mock_executor):
    return SkillRegistry(skill_dirs=[skill_dir], executor=mock_executor)


def test_registry_loads_skills(registry):
    registry.load()
    assert len(registry.list_skills()) == 2


def test_registry_get_skill(registry):
    registry.load()
    skill = registry.get("commit")
    assert skill is not None
    assert skill.name == "commit"


def test_registry_get_missing(registry):
    registry.load()
    assert registry.get("nonexistent") is None


def test_registry_list_skills(registry):
    registry.load()
    skills = registry.list_skills()
    names = [s["name"] for s in skills]
    assert "commit" in names
    assert "review" in names


@pytest.mark.asyncio
async def test_registry_execute(registry, mock_executor):
    registry.load()
    result = await registry.execute("commit", args={"message": "fix"})
    assert result["success"]
    mock_executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_registry_execute_missing(registry):
    registry.load()
    result = await registry.execute("nonexistent", args={})
    assert not result["success"]
    assert "not found" in result["response"].lower()


def test_parse_slash_command():
    name, args = SkillRegistry.parse_command("/commit -m 'fix bug'")
    assert name == "commit"


def test_parse_slash_command_no_args():
    name, args = SkillRegistry.parse_command("/review")
    assert name == "review"
    assert args == ""
