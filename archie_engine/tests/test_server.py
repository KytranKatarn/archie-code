import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from archie_engine.server import EngineServer


@pytest_asyncio.fixture
async def server():
    srv = EngineServer(host="127.0.0.1", port=0)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.mark.asyncio
async def test_server_starts_and_stops(server):
    assert server.is_running


@pytest.mark.asyncio
async def test_ping_pong(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "pong"


@pytest.mark.asyncio
async def test_multiple_connections(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        await ws1.send(json.dumps({"type": "ping"}))
        await ws2.send(json.dumps({"type": "ping"}))
        r1 = json.loads(await asyncio.wait_for(ws1.recv(), timeout=5))
        r2 = json.loads(await asyncio.wait_for(ws2.recv(), timeout=5))
        assert r1["type"] == "pong"
        assert r2["type"] == "pong"


@pytest.mark.asyncio
async def test_custom_handler(server):
    async def echo_handler(msg):
        return {"type": "response", "content": msg.get("content", "")}

    server.set_handler(echo_handler)
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "message", "content": "hello"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "response"
        assert response["content"] == "hello"


@pytest.mark.asyncio
async def test_malformed_json(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send("not json at all")
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "error"
        assert "json" in response["error"].lower() or "JSON" in response["error"]


@pytest.mark.asyncio
async def test_non_object_json_frame(server):
    """A valid-JSON non-object frame (e.g. 42) must return a clean error frame,
    not raise AttributeError and drop the connection."""
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps(42))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "error"
        # Connection must survive — a follow-up ping still works.
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_streaming_handler_emits_progress_then_response(server):
    """A handler that accepts an optional `send` coroutine can emit intermediate
    frames BEFORE its final return value. The server delivers them in order over
    the same connection, then delivers the returned frame last (#cli-streaming)."""
    async def stream_handler(msg, send=None):
        if send is not None:
            await send({"type": "progress", "stage": "a", "detail": "1"})
            await send({"type": "progress", "stage": "b", "detail": "2"})
        return {"type": "response", "content": "done"}

    server.set_handler(stream_handler)
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "message", "content": "go"}))
        f1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        f2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        f3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert f1["type"] == "progress" and f1["stage"] == "a"
        assert f2["type"] == "progress" and f2["stage"] == "b"
        assert f3["type"] == "response" and f3["content"] == "done"


@pytest.mark.asyncio
async def test_legacy_msg_only_handler_still_single_response(server):
    """Backward compat: a handler with the legacy (msg) signature — no `send`
    param — must be called exactly as before and yield exactly one frame."""
    async def legacy_handler(msg):
        return {"type": "response", "content": msg.get("content", "")}

    server.set_handler(legacy_handler)
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "message", "content": "hi"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp == {"type": "response", "content": "hi"}
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert pong["type"] == "pong"
