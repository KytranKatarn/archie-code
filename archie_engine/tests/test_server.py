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
