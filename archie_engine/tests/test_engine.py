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


@pytest.mark.asyncio
async def test_process_chat_message_streams_progress(tmp_path):
    """With stream=True and a `send` callback, the engine emits a `progress`
    frame for the dispatch step BEFORE the final response (#cli-streaming)."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    engine.router.route = AsyncMock(return_value={"response": "answer"})

    frames = []

    async def capture(frame):
        frames.append(frame)

    result = await engine._process_chat_message(
        {"type": "message", "content": "What is the Bridge dispatcher?", "stream": True},
        send=capture,
    )

    assert result["type"] == "response"
    assert result["content"] == "answer"
    progress = [f for f in frames if f.get("type") == "progress"]
    assert progress, "expected at least one progress frame when streaming"
    assert progress[0]["stage"] == "dispatch"
    assert progress[0]["session_id"] == result["session_id"]
    await engine.db.close()


@pytest.mark.asyncio
async def test_process_chat_message_no_stream_no_progress(tmp_path):
    """Backward compat: without stream=True, NO progress frames are emitted even
    if a send callback is available — legacy one-shot clients see only the reply."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    engine.router.route = AsyncMock(return_value={"response": "answer"})

    frames = []

    async def capture(frame):
        frames.append(frame)

    result = await engine._process_chat_message(
        {"type": "message", "content": "What is the Bridge dispatcher?"},
        send=capture,
    )

    assert result["type"] == "response"
    assert frames == []
    await engine.db.close()


@pytest.mark.asyncio
async def test_process_chat_message_includes_badge_fields(tmp_path):
    """Task 7: the response frame carries agent/node/model provenance for the TUI
    badge. Local inference -> agent defaults to A.R.C.H.I.E., node=local, model
    from the router's model_used."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    engine.router.route = AsyncMock(
        return_value={"response": "answer", "model_used": "test-model",
                      "agent_name": "F.O.R.G.E.", "node": "Starship-246"}
    )
    result = await engine._process_chat_message(
        {"type": "message", "content": "What is the Bridge dispatcher?"}
    )
    assert result["type"] == "response"
    assert result["agent"] == "F.O.R.G.E."
    assert result["node"] == "Starship-246"
    assert result["model"] == "test-model"
    await engine.db.close()


@pytest.mark.asyncio
async def test_list_tools_returns_tool_definitions(tmp_path):
    """Task 5 (tool palette): the engine exposes its MCP tool definitions to the TUI."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    try:
        resp = await engine.handle_message({"type": "list_tools"})
        assert resp["type"] == "tools_list"
        assert isinstance(resp["tools"], list) and len(resp["tools"]) > 0
        assert all("name" in t for t in resp["tools"])
    finally:
        await engine.db.close()


@pytest.mark.asyncio
async def test_build_frame_streams_progress_and_returns_result(tmp_path):
    """Task 5 (driveable build loop): a `build` frame drives run_build, forwards a
    progress callback that streams `progress` frames, and returns a build_result."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()

    async def fake_run_build(task, **kwargs):
        prog = kwargs.get("progress")
        if prog is not None:
            await prog("test", "pytest")
        return {"success": True, "stage": "done", "pr_url": "https://gh/pr/1",
                "branch": "engine/x", "files": [], "duration_ms": 5,
                "target": "archie-code", "error": "", "pr_number": 1}

    engine.run_build = fake_run_build
    frames = []

    async def capture(f):
        frames.append(f)

    try:
        resp = await engine.handle_message({"type": "build", "task": "add X"}, send=capture)
        assert resp["type"] == "build_result"
        assert resp["success"] is True and resp["pr_url"] == "https://gh/pr/1"
        assert any(f.get("type") == "progress" and f.get("stage") == "test" for f in frames)
    finally:
        await engine.db.close()


@pytest.mark.asyncio
async def test_session_send_records_and_resolves_link(tmp_path):
    """Task 6: session_send records a message and returns the linked conversation."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    try:
        s = await engine.sessions.create(working_dir="/tmp")
        await engine.sessions.link_conversation(s["id"], "conv-9")
        result = await engine._do_session_send(s["id"], "hello from claude")
        assert result["session_id"] == s["id"]
        assert result["conversation_id"] == "conv-9"
        assert result["message_id"] is not None
        assert await engine.sessions.get_linked_conversation(s["id"]) == "conv-9"
    finally:
        await engine.db.close()


@pytest.mark.asyncio
async def test_mcp_tools_include_session_send(tmp_path):
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    names = [t["name"] for t in engine.mcp_server.get_tool_definitions()]
    assert "session_send" in names


@pytest.mark.asyncio
async def test_link_conversation_frame(tmp_path):
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    try:
        s = await engine.sessions.create(working_dir="/tmp")
        resp = await engine.handle_message({
            "type": "link_conversation", "session_id": s["id"], "conversation_id": "conv-x",
        })
        assert resp["type"] == "conversation_linked"
        assert resp["conversation_id"] == "conv-x"
    finally:
        await engine.db.close()


@pytest.mark.asyncio
async def test_session_send_via_mcp_handler(tmp_path):
    """The MCP sync handler runs tool code on a SEPARATE loop/thread when the
    engine loop is running; session_send must be loop-safe there (fresh conn)."""
    config = EngineConfig(data_dir=tmp_path, hub_url="", hub_api_key="")
    engine = Engine(config)
    await engine.db.initialize()
    try:
        s = await engine.sessions.create(working_dir="/tmp")
        await engine.sessions.link_conversation(s["id"], "conv-mcp")
        # SYNC handler; inside a running loop -> ThreadPoolExecutor + asyncio.run path.
        out = engine._mcp_tool_handler(
            "session_send", {"session_id": s["id"], "content": "hi via mcp"}
        )
        assert "conv-mcp" in out.get("output", "")
        assert out.get("conversation_id") == "conv-mcp"
    finally:
        await engine.db.close()
