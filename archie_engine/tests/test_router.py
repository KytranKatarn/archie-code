import pytest
from unittest.mock import AsyncMock, MagicMock
from archie_engine.router import CommandRouter
from archie_engine.tools import ToolRegistry
from archie_engine.tools.base import ToolResult


@pytest.fixture
def mock_tools():
    registry = ToolRegistry()

    mock_file = MagicMock()
    mock_file.name = "file_ops"
    mock_file.description = "File ops"
    mock_file.to_dict = MagicMock(return_value={"name": "file_ops", "description": "File ops"})
    mock_file.execute = AsyncMock(return_value=ToolResult(success=True, output="file content here"))
    registry.register(mock_file)

    mock_git = MagicMock()
    mock_git.name = "git_ops"
    mock_git.description = "Git ops"
    mock_git.to_dict = MagicMock(return_value={"name": "git_ops", "description": "Git ops"})
    mock_git.execute = AsyncMock(return_value=ToolResult(success=True, output="On branch main"))
    registry.register(mock_git)

    mock_shell = MagicMock()
    mock_shell.name = "shell_ops"
    mock_shell.description = "Shell ops"
    mock_shell.to_dict = MagicMock(return_value={"name": "shell_ops", "description": "Shell ops"})
    mock_shell.execute = AsyncMock(return_value=ToolResult(success=True, output="test passed"))
    registry.register(mock_shell)

    return registry


@pytest.fixture
def mock_inference():
    client = AsyncMock()
    client.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Here's the fix..."},
        "model": "qwen2.5:7b",
    })
    return client


@pytest.fixture
def router(mock_tools, mock_inference):
    return CommandRouter(tools=mock_tools, inference=mock_inference)


@pytest.mark.asyncio
async def test_route_file_operation(router):
    intent = {"type": "file_operation", "confidence": 0.9, "raw_input": "read config.py", "entities": {"files": ["config.py"]}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["success"]


@pytest.mark.asyncio
async def test_route_git_operation(router):
    intent = {"type": "git_operation", "confidence": 0.9, "raw_input": "git status", "entities": {}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["success"]


@pytest.mark.asyncio
async def test_route_shell_command(router):
    intent = {"type": "shell_command", "confidence": 0.9, "raw_input": "run npm test", "entities": {}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["success"]


@pytest.mark.asyncio
async def test_route_conversation_uses_llm(router, mock_inference):
    intent = {"type": "conversation", "confidence": 0.8, "raw_input": "hello", "entities": {}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["response"]
    mock_inference.chat.assert_called_once()


@pytest.mark.asyncio
async def test_route_code_task_uses_llm(router, mock_inference):
    intent = {"type": "code_task", "confidence": 0.9, "raw_input": "fix the bug", "entities": {}}
    context = {"working_dir": "/tmp", "history": []}
    result = await router.route(intent, context=context)
    mock_inference.chat.assert_called_once()


@pytest.mark.asyncio
async def test_route_tool_error_handled(router, mock_tools):
    mock_tools.get("file_ops").execute = AsyncMock(
        return_value=ToolResult(success=False, error="file not found")
    )
    intent = {"type": "file_operation", "confidence": 0.9, "raw_input": "read missing.py", "entities": {"files": ["missing.py"]}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert not result["success"]


@pytest.mark.asyncio
async def test_route_platform_dispatch(mock_tools, mock_inference):
    """When hub connector is provided, platform intents dispatch through it."""
    mock_hub = AsyncMock()
    mock_hub.dispatch = AsyncMock(return_value={
        "response": "Code review complete. Found 2 issues.",
        "agent_name": "S.H.I.E.L.D.",
        "model": "qwen2.5:7b",
    })

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review auth module"}
    context = {"working_dir": "/tmp", "history": []}

    result = await router.route(intent, context, dispatch_target="platform", capability="code_review")
    assert result["success"] is True
    assert "S.H.I.E.L.D." in result["response"] or "Code review" in result["response"]
    assert result["model_used"] is not None
    mock_hub.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_platform_dispatch_logs_job(mock_tools, mock_inference):
    """After successful platform dispatch, log_job should be called."""
    from unittest.mock import AsyncMock

    mock_hub = AsyncMock()
    mock_hub.dispatch = AsyncMock(return_value={
        "response": "Review complete.",
        "agent_name": "S.H.I.E.L.D.",
        "model": "qwen2.5:7b",
    })
    mock_hub.log_job = AsyncMock(return_value={"success": True, "job_id": 99})

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review auth"}
    context = {"working_dir": "/tmp", "history": []}

    await router.route(intent, context, dispatch_target="platform", capability="code_review")
    mock_hub.log_job.assert_called_once()


@pytest.mark.asyncio
async def test_kb_enrichment_adds_context_to_prompt(mock_tools, mock_inference):
    """When hub has KB results, they're injected into the system prompt."""
    mock_hub = AsyncMock()
    mock_hub.search_knowledge = AsyncMock(return_value={
        "results": [
            {"title": "Auth Middleware", "content": "The auth middleware validates JWT tokens..."},
        ]
    })

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "knowledge_query", "confidence": 0.8, "raw_input": "how does auth work?", "entities": {}}
    await router.route(intent, context={"working_dir": "/tmp"})

    # Verify search_knowledge was called
    mock_hub.search_knowledge.assert_called_once_with("how does auth work?", limit=3)

    # Verify the system prompt includes KB context
    call_kwargs = mock_inference.chat.call_args
    system_prompt = call_kwargs.kwargs.get("system", "") or call_kwargs[1].get("system", "")
    assert "Auth Middleware" in system_prompt


@pytest.mark.asyncio
async def test_kb_enrichment_graceful_when_no_hub(router, mock_inference):
    """Without hub connector, KB enrichment is skipped gracefully."""
    intent = {"type": "conversation", "confidence": 0.8, "raw_input": "hello", "entities": {}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["response"]  # still works
    mock_inference.chat.assert_called_once()


@pytest.mark.asyncio
async def test_kb_enrichment_graceful_on_error(mock_tools, mock_inference):
    """If KB search throws, inference still completes."""
    mock_hub = AsyncMock()
    mock_hub.search_knowledge = AsyncMock(side_effect=Exception("hub unreachable"))

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "conversation", "confidence": 0.8, "raw_input": "hello", "entities": {}}
    result = await router.route(intent, context={"working_dir": "/tmp"})
    assert result["response"]  # still works despite KB error


@pytest.mark.asyncio
async def test_kb_enrichment_on_code_task(mock_tools, mock_inference):
    """Code tasks also get KB enrichment when hub is connected."""
    mock_hub = AsyncMock()
    mock_hub.search_knowledge = AsyncMock(return_value={
        "results": [
            {"title": "Coding Standards", "content": "Use Black formatter, type hints required..."},
        ]
    })

    router = CommandRouter(
        tools=mock_tools, inference=mock_inference, hub_connector=mock_hub
    )

    intent = {"type": "code_task", "confidence": 0.9, "raw_input": "fix the auth bug", "entities": {}}
    await router.route(intent, context={"working_dir": "/tmp", "history": []})

    mock_hub.search_knowledge.assert_called_once()
    call_kwargs = mock_inference.chat.call_args
    system_prompt = call_kwargs.kwargs.get("system", "") or call_kwargs[1].get("system", "")
    assert "Coding Standards" in system_prompt
