import pytest
import pytest_asyncio
import asyncio
from unittest.mock import AsyncMock, MagicMock
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub import HubStatus


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.auth = MagicMock()
    # Client mode: connectivity is proven by the hub health endpoint
    # (no fleet-node registration anymore).
    conn.health_check = AsyncMock(return_value={"status": "healthy"})
    return conn


@pytest_asyncio.fixture
async def heartbeat(mock_connector):
    hb = Heartbeat(connector=mock_connector, interval=1)
    yield hb
    await hb.stop()


@pytest.mark.asyncio
async def test_start_connects_via_health(heartbeat, mock_connector):
    await heartbeat.start()
    mock_connector.health_check.assert_called()
    assert heartbeat.status == HubStatus.CONNECTED


@pytest.mark.asyncio
async def test_stop(heartbeat):
    await heartbeat.start()
    assert heartbeat.is_running
    await heartbeat.stop()
    assert not heartbeat.is_running


@pytest.mark.asyncio
async def test_keepalive_probes_periodically(heartbeat, mock_connector):
    await heartbeat.start()
    await asyncio.sleep(2.5)
    # 1 connect probe + at least one keepalive probe
    assert mock_connector.health_check.call_count >= 2


@pytest.mark.asyncio
async def test_health_error_sets_offline(mock_connector):
    mock_connector.health_check = AsyncMock(return_value={"error": "refused", "status": 0})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.OFFLINE
    await hb.stop()


@pytest.mark.asyncio
async def test_auth_failure_sets_auth_failed(mock_connector):
    mock_connector.health_check = AsyncMock(return_value={"error": "unauthorized", "status": 401})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.AUTH_FAILED
    await hb.stop()


@pytest.mark.asyncio
async def test_keepalive_restores_connection(mock_connector):
    """A failed-then-recovered health probe flips OFFLINE back to CONNECTED."""
    hb = Heartbeat(connector=mock_connector, interval=1)
    hb.status = HubStatus.OFFLINE
    mock_connector.health_check = AsyncMock(return_value={"status": "healthy"})
    await hb._send_one_heartbeat()
    assert hb.status == HubStatus.CONNECTED
