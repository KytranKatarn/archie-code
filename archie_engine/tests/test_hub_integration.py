import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from unittest.mock import AsyncMock, MagicMock
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig
from archie_engine.hub import HubStatus


@pytest_asyncio.fixture
async def engine_no_hub(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest_asyncio.fixture
async def engine_with_hub(tmp_path):
    config = EngineConfig(
        data_dir=tmp_path,
        ws_port=0,
        hub_url="http://fake-hub:3000",
        hub_api_key="test-key",
    )
    eng = Engine(config)
    # Mock connector to avoid real HTTP. Client mode: connectivity is proven
    # by the health probe (no fleet-node registration).
    if eng.hub_connector:
        eng.hub_connector.auth = MagicMock()
        eng.hub_connector.health_check = AsyncMock(return_value={"status": "ok"})
        eng.hub_connector.get = AsyncMock(return_value={"status": "ok"})
        eng.hub_connector.post = AsyncMock(return_value={"status": "ok"})
        eng.hub_connector.get_skills = AsyncMock(return_value={"skills": []})
        eng.hub_connector.list_agents = AsyncMock(return_value={"agents": []})
        eng.hub_connector.get_model_state = AsyncMock(return_value={"models": []})
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_without_hub(engine_no_hub):
    assert engine_no_hub.is_running
    assert engine_no_hub.hub_status == HubStatus.DISCONNECTED
    assert engine_no_hub.hub_connector is None


@pytest.mark.asyncio
async def test_engine_with_hub_configured(engine_with_hub):
    assert engine_with_hub.is_running
    assert engine_with_hub.hub_connector is not None
    assert engine_with_hub.hub_status == HubStatus.CONNECTED


@pytest.mark.asyncio
async def test_hub_status_via_websocket(engine_no_hub):
    uri = f"ws://{engine_no_hub.config.ws_host}:{engine_no_hub.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "hub_status"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "hub_status"
        assert response["hub_status"] == "disconnected"


@pytest.mark.asyncio
async def test_hub_status_connected_via_websocket(engine_with_hub):
    uri = f"ws://{engine_with_hub.config.ws_host}:{engine_with_hub.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "hub_status"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        # Client mode: connected, but no fleet node_id is minted.
        assert response["hub_status"] == "connected"


@pytest.mark.asyncio
async def test_client_connect_and_dispatch(tmp_path):
    """Client-mode lifecycle: health connect -> delegate to the hub team -> inbound work."""
    config = EngineConfig(
        data_dir=tmp_path,
        hub_url="http://192.168.1.200:3000",
        hub_api_key="test-key",
    )
    engine = Engine(config)

    # Hub mocks (client mode — no node registration)
    engine.hub_connector.health_check = AsyncMock(return_value={"status": "healthy"})
    engine.hub_connector.post = AsyncMock(return_value={"task_id": 4242, "status": "queued"})
    engine.hub_connector.get_personality = AsyncMock(return_value={"error": "not found"})

    # Router mocked to avoid needing Ollama
    engine.router.route = AsyncMock(return_value={
        "response": "No security issues found in main.py",
        "success": True,
    })

    # 1. Connect via health probe (no registration)
    await engine.hub_heartbeat._register()
    assert engine.hub_heartbeat.status == HubStatus.CONNECTED

    # 2. Dispatch delegates to the team via the internal delegation surface
    result = await engine.hub_connector.dispatch("review main.py", agent_target="capability:code")
    assert result["task_id"] == 4242
    assert "response" in result
    posted_path = engine.hub_connector.post.call_args.args[0]
    assert posted_path == "/api/internal/delegation/submit"

    # 3. Inbound work still routes locally
    await engine.db.initialize()
    result = await engine.handle_inbound_job({
        "task": "Review main.py for security issues",
        "context": {"files": ["main.py"]},
        "source": "hub_dispatch",
    })
    assert result["success"] is True
    assert result["response"] == "No security issues found in main.py"
    await engine.db.close()
