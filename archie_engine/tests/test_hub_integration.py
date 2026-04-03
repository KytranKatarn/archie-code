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
    # Mock connector to avoid real HTTP calls
    if eng.hub_connector:
        auth_mock = MagicMock()
        auth_mock.load_node_id = MagicMock(return_value=None)
        auth_mock.load_node_key = MagicMock(return_value=None)
        eng.hub_connector.auth = auth_mock
        eng.hub_connector.get = AsyncMock(return_value={"status": "ok"})
        eng.hub_connector.post = AsyncMock(return_value={"status": "ok"})
        eng.hub_connector.register_node = AsyncMock(return_value={
            "success": True, "node": {"node_id": "test-123"}, "api_key": "key123"
        })
        eng.hub_connector.send_heartbeat = AsyncMock(return_value={"status": "ok"})
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
        assert response["hub_status"] == "connected"
        assert response["node_id"] == "test-123"
