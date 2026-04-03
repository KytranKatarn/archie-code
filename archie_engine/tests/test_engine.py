import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from unittest.mock import AsyncMock
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest_asyncio.fixture
async def engine(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_starts_and_stops(engine):
    assert engine.is_running


@pytest.mark.asyncio
async def test_engine_creates_session(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_create", "working_dir": "/tmp"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "session_created"
        assert response.get("session_id") is not None


@pytest.mark.asyncio
async def test_engine_ping(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "pong"


@pytest.mark.asyncio
async def test_engine_processes_message(engine):
    """E2E: send a message, get a response (may error on inference but shouldn't crash)."""
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "git status",
        }))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert response["type"] == "response"
        assert "session_id" in response
        assert "intent" in response


@pytest.mark.asyncio
async def test_engine_session_resume(engine):
    """Create a session then resume it."""
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_create", "working_dir": "/tmp"}))
        created = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        session_id = created["session_id"]

        await ws.send(json.dumps({"type": "session_resume", "session_id": session_id}))
        resumed = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resumed["type"] == "session_resumed"
        assert resumed["session_id"] == session_id


@pytest.mark.asyncio
async def test_engine_session_resume_not_found(engine):
    """Resume a non-existent session returns error."""
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "session_resume", "session_id": "nonexistent"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "error"


@pytest.mark.asyncio
async def test_engine_unknown_message_type(engine):
    """Unknown message type returns error."""
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "frobnicate"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "error"


@pytest.mark.asyncio
async def test_engine_dispatch_decision_in_response():
    """Engine responses should include dispatch_target field."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            await ws.send(json.dumps({
                "type": "message",
                "content": "What is the Bridge dispatcher?",
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            assert resp["type"] == "response"
            assert "dispatch_target" in resp
            assert resp["dispatch_target"] == "local"
            assert resp["intent"] == "knowledge_query"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_shell_not_triggered_by_questions():
    """Regression: natural language questions must not run as shell commands."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            await ws.send(json.dumps({
                "type": "message",
                "content": "What models are available?",
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            assert resp["intent"] != "shell_command", \
                f"Question classified as shell_command — intent parser bug not fixed"
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_delegation():
    """Engine handles delegated tasks from Claude."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            await ws.send(json.dumps({
                "type": "delegate",
                "task": "read the config file",
                "files": ["config.py"],
                "expected_outcome": "file contents",
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            assert resp["type"] == "delegation_result"
            assert "task" in resp
            assert "success" in resp
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_state_sync():
    """Engine handles incoming state sync events."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999")
    engine = Engine(config)
    await engine.start()

    try:
        async with websockets.connect(f"ws://127.0.0.1:{engine.server.port}") as ws:
            await ws.send(json.dumps({
                "type": "state_sync",
                "event": {
                    "kind": "file_changed",
                    "data": {"file": "main.py", "action": "edit", "source": "claude"},
                },
            }))
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            assert resp["type"] == "sync_ack"
            assert "conflicts" in resp
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_engine_has_learning_store(tmp_path):
    """Engine should have a learning store."""
    config = EngineConfig(ws_port=0, ollama_host="http://localhost:99999", data_dir=tmp_path)
    engine = Engine(config)
    await engine.start()

    try:
        assert engine.learning_store is not None
        engine.learning_store.record(
            intent_type="code_task", task_summary="test learning",
            resolution="test resolution", source="test",
        )
        assert len(engine.learning_store.get_all()) == 1
    finally:
        await engine.stop()


@pytest.mark.asyncio
async def test_handle_inbound_job_processes_task(tmp_path):
    """Engine should process inbound hub-dispatched jobs."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)

    # Initialize DB for session creation
    await engine.db.initialize()

    # Mock the router to avoid needing Ollama
    engine.router.route = AsyncMock(return_value={
        "response": "Code looks clean, no issues found.",
        "success": True,
    })

    result = await engine.handle_inbound_job({
        "task": "Review main.py for security issues",
        "context": {"files": ["main.py"]},
        "source": "hub_dispatch",
    })

    assert result["success"] is True
    assert "response" in result
    assert result["response"] == "Code looks clean, no issues found."
    await engine.db.close()


@pytest.mark.asyncio
async def test_handle_inbound_job_returns_error_on_failure(tmp_path):
    """Engine should return error dict if router raises."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()

    engine.router.route = AsyncMock(side_effect=Exception("Model unavailable"))

    result = await engine.handle_inbound_job({
        "task": "Do something",
        "context": {},
        "source": "hub_dispatch",
    })

    assert result["success"] is False
    assert "error" in result
    await engine.db.close()
