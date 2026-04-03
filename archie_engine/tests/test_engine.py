import pytest
import pytest_asyncio
import json
import asyncio
import websockets
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
