import pytest
from unittest.mock import AsyncMock, MagicMock
from archie_engine.skills.skill import Skill
from archie_engine.skills.executor import SkillExecutor
from archie_engine.tools import ToolRegistry
from archie_engine.tools.base import ToolResult


@pytest.fixture
def mock_inference():
    client = AsyncMock()
    client.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Done! Committed as abc123."},
        "model": "qwen2.5:7b",
    })
    return client


@pytest.fixture
def mock_tools():
    registry = ToolRegistry()
    mock_git = MagicMock()
    mock_git.name = "git_ops"
    mock_git.description = "Git"
    mock_git.to_dict = MagicMock(return_value={"name": "git_ops", "description": "Git"})
    mock_git.execute = AsyncMock(return_value=ToolResult(success=True, output="diff output"))
    registry.register(mock_git)
    return registry


@pytest.fixture
def executor(mock_inference, mock_tools):
    return SkillExecutor(inference=mock_inference, tools=mock_tools, default_model="qwen2.5:7b")


@pytest.fixture
def commit_skill():
    return Skill(
        name="commit",
        description="Create a git commit",
        arguments=[{"name": "message", "required": False}],
        body="Create a commit.\n1. Run git diff --staged\n2. Generate message\n3. Commit",
    )


@pytest.mark.asyncio
async def test_execute_skill(executor, commit_skill):
    result = await executor.execute(commit_skill, args={})
    assert result["success"]
    assert result["response"]


@pytest.mark.asyncio
async def test_execute_skill_with_args(executor, commit_skill):
    result = await executor.execute(commit_skill, args={"message": "fix bug"})
    assert result["success"]


@pytest.mark.asyncio
async def test_execute_renders_args_in_prompt(executor, commit_skill, mock_inference):
    await executor.execute(commit_skill, args={"message": "my message"})
    call_args = mock_inference.chat.call_args
    messages = call_args[1].get("messages") or call_args[0][0]
    prompt_text = " ".join(m["content"] for m in messages)
    assert "my message" in prompt_text


@pytest.mark.asyncio
async def test_execute_returns_model_used(executor, commit_skill):
    result = await executor.execute(commit_skill, args={})
    assert result.get("model_used") == "qwen2.5:7b"
