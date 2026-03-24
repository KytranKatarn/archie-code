import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub import HubStatus


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.register_node = AsyncMock(return_value={"node_id": "test-node"})
    conn.send_heartbeat = AsyncMock(return_value={"status": "ok"})
    return conn


@pytest_asyncio.fixture
async def heartbeat(mock_connector):
    hb = Heartbeat(connector=mock_connector, interval=1)
    yield hb
    await hb.stop()


@pytest.mark.asyncio
async def test_start_registers_node(heartbeat, mock_connector):
    await heartbeat.start()
    mock_connector.register_node.assert_called_once()
    assert heartbeat.status == HubStatus.CONNECTED
    assert heartbeat.node_id == "test-node"


@pytest.mark.asyncio
async def test_stop(heartbeat):
    await heartbeat.start()
    assert heartbeat.is_running
    await heartbeat.stop()
    assert not heartbeat.is_running


@pytest.mark.asyncio
async def test_heartbeat_sends_periodically(heartbeat, mock_connector):
    await heartbeat.start()
    await asyncio.sleep(2.5)
    assert mock_connector.send_heartbeat.call_count >= 2


@pytest.mark.asyncio
async def test_connection_failure_sets_offline(mock_connector):
    mock_connector.register_node = AsyncMock(return_value={"error": "refused", "status": 0})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.OFFLINE
    await hb.stop()


@pytest.mark.asyncio
async def test_auth_failure_sets_auth_failed(mock_connector):
    mock_connector.register_node = AsyncMock(return_value={"error": "unauthorized", "status": 401})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.AUTH_FAILED
    await hb.stop()
