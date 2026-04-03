import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub import HubStatus


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    # Auth mock: no persisted credentials by default
    conn.auth = MagicMock()
    conn.auth.load_node_id = MagicMock(return_value=None)
    conn.auth.load_node_key = MagicMock(return_value=None)
    conn.register_node = AsyncMock(return_value={
        "success": True, "node": {"node_id": "test-node"}, "api_key": "key123"
    })
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


@pytest.mark.asyncio
async def test_register_sends_system_info(mock_connector):
    """Registration should send real system info."""
    hb = Heartbeat(connector=mock_connector)
    mock_connector.register_node = AsyncMock(return_value={
        "success": True, "node": {"node_id": "node_abc"}, "api_key": "key123"
    })
    await hb._register()
    call_kwargs = mock_connector.register_node.call_args[1]
    assert "node_name" in call_kwargs
    assert "cpu_cores" in call_kwargs
    assert "ram_gb" in call_kwargs


@pytest.mark.asyncio
async def test_heartbeat_sends_real_metrics(mock_connector):
    """Heartbeat should send CPU/memory metrics."""
    hb = Heartbeat(connector=mock_connector)
    hb.node_id = "node_abc"
    hb.status = HubStatus.CONNECTED
    mock_connector.send_heartbeat = AsyncMock(return_value={"success": True})
    await hb._send_one_heartbeat()
    call_kwargs = mock_connector.send_heartbeat.call_args[1]
    metrics = call_kwargs["metrics"]
    assert "cpu_usage" in metrics
    assert "memory_usage" in metrics
    assert "client_version" in metrics


@pytest.mark.asyncio
async def test_persisted_node_id_reused(tmp_path):
    """If credentials are persisted, skip fresh registration."""
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_id("node_persisted_123")
    auth.store_node_key("key_persisted_456")

    from archie_engine.hub.connector import HubConnector
    connector = HubConnector(hub_url="http://test:3000", auth=auth)
    connector.send_heartbeat = AsyncMock(return_value={"success": True})
    connector.register_node = AsyncMock()

    hb = Heartbeat(connector=connector)
    await hb._register()
    assert hb.node_id == "node_persisted_123"
    assert hb.status == HubStatus.CONNECTED
    connector.register_node.assert_not_called()
