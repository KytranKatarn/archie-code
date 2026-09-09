import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from archie_engine.server import EngineServer


TOKEN = "t-test-token"


@pytest_asyncio.fixture
async def server():
    srv = EngineServer(host="127.0.0.1", port=0, token=TOKEN)
    await srv.start()
    yield srv
    await srv.stop()


def _auth(token: str = TOKEN) -> dict:
    return {"additional_headers": {"Authorization": f"Bearer {token}"}}


def _uri(server) -> str:
    return f"ws://{server.host}:{server.port}"


@pytest.mark.asyncio
async def test_server_starts_and_stops(server):
    assert server.is_running


@pytest.mark.asyncio
async def test_ping_pong(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri, **_auth()) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "pong"


@pytest.mark.asyncio
async def test_multiple_connections(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri, **_auth()) as ws1, websockets.connect(uri, **_auth()) as ws2:
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
    async with websockets.connect(uri, **_auth()) as ws:
        await ws.send(json.dumps({"type": "message", "content": "hello"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "response"
        assert response["content"] == "hello"


@pytest.mark.asyncio
async def test_malformed_json(server):
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri, **_auth()) as ws:
        await ws.send("not json at all")
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "error"
        assert "json" in response["error"].lower() or "JSON" in response["error"]


@pytest.mark.asyncio
async def test_non_object_json_frame(server):
    """A valid-JSON non-object frame (e.g. 42) must return a clean error frame,
    not raise AttributeError and drop the connection."""
    uri = f"ws://{server.host}:{server.port}"
    async with websockets.connect(uri, **_auth()) as ws:
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
    async with websockets.connect(uri, **_auth()) as ws:
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
    async with websockets.connect(uri, **_auth()) as ws:
        await ws.send(json.dumps({"type": "message", "content": "hi"}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert resp == {"type": "response", "content": "hi"}
        await ws.send(json.dumps({"type": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert pong["type"] == "pong"


# ── #6657: the handshake gate ───────────────────────────────────────────────
# Every assertion here is against the HTTP handshake: an unauthenticated peer
# never reaches _process_message. Reproduced live before the fix from a sibling
# container (file_tree root=/ listed the engine's root fs).


@pytest.mark.asyncio
async def test_no_bearer_is_rejected_at_handshake(server):
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        async with websockets.connect(_uri(server)):
            pass
    assert ei.value.response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_bearer_is_rejected(server):
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        async with websockets.connect(_uri(server), **_auth("nope")):
            pass
    assert ei.value.response.status_code == 401


@pytest.mark.asyncio
async def test_bearer_scheme_is_required(server):
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        async with websockets.connect(_uri(server), additional_headers={"Authorization": TOKEN}):
            pass
    assert ei.value.response.status_code == 401


@pytest.mark.asyncio
async def test_unset_server_token_rejects_everyone():
    """Fail CLOSED: no ENGINE_WS_TOKEN ⇒ nothing connects, not even an empty bearer."""
    srv = EngineServer(host="127.0.0.1", port=0, token="")
    await srv.start()
    try:
        assert srv.auth_configured is False
        for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer x"}):
            with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
                async with websockets.connect(_uri(srv), additional_headers=headers):
                    pass
            assert ei.value.response.status_code == 401
    finally:
        await srv.stop()


@pytest.mark.asyncio
async def test_right_bearer_reaches_the_message_surface(server):
    async with websockets.connect(_uri(server), **_auth()) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        assert json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["type"] == "pong"


@pytest.mark.asyncio
async def test_browser_origin_is_refused_by_default(server):
    """A browser cannot set Authorization on a ws, so an Origin can only mean a
    cross-site page trying its luck — 403 unless explicitly allowlisted."""
    with pytest.raises(websockets.exceptions.InvalidStatus) as ei:
        async with websockets.connect(_uri(server), origin="http://evil.example", **_auth()):
            pass
    assert ei.value.response.status_code == 403


@pytest.mark.asyncio
async def test_allowlisted_origin_is_accepted():
    srv = EngineServer(host="127.0.0.1", port=0, token=TOKEN, allowed_origins=["http://ok.example"])
    await srv.start()
    try:
        async with websockets.connect(_uri(srv), origin="http://ok.example", **_auth()) as ws:
            await ws.send(json.dumps({"type": "ping"}))
            assert json.loads(await asyncio.wait_for(ws.recv(), timeout=5))["type"] == "pong"
    finally:
        await srv.stop()


def test_token_comes_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("ENGINE_WS_TOKEN", "  from-env  ")
    monkeypatch.setenv("ENGINE_WS_ALLOWED_ORIGINS", "http://a, http://b ,")
    srv = EngineServer(host="127.0.0.1", port=0)
    assert srv._bearer_ok("Bearer from-env") is True
    assert srv._bearer_ok("bearer from-env") is True  # scheme is case-insensitive
    assert srv._bearer_ok("Bearer from-env2") is False
    assert srv._allowed_origins == {"http://a", "http://b"}
