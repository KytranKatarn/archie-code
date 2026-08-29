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
    # Client mode: connectivity is proven by an AUTHENTICATED probe (#6037) —
    # health_check requires no auth and cannot certify authorization.
    conn.auth_check = AsyncMock(return_value={"status": "ok"})
    return conn


@pytest_asyncio.fixture
async def heartbeat(mock_connector):
    hb = Heartbeat(connector=mock_connector, interval=1)
    yield hb
    await hb.stop()


@pytest.mark.asyncio
async def test_start_connects_via_health(heartbeat, mock_connector):
    await heartbeat.start()
    mock_connector.auth_check.assert_called()
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
    assert mock_connector.auth_check.call_count >= 2


@pytest.mark.asyncio
async def test_health_error_sets_offline(mock_connector):
    mock_connector.auth_check = AsyncMock(return_value={"error": "refused", "status": 0})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.OFFLINE
    await hb.stop()


@pytest.mark.asyncio
async def test_auth_failure_sets_auth_failed(mock_connector):
    mock_connector.auth_check = AsyncMock(return_value={"error": "unauthorized", "status": 401})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.AUTH_FAILED
    await hb.stop()


@pytest.mark.asyncio
async def test_keepalive_restores_connection(mock_connector):
    """A failed-then-recovered health probe flips OFFLINE back to CONNECTED."""
    hb = Heartbeat(connector=mock_connector, interval=1)
    hb.status = HubStatus.OFFLINE
    mock_connector.auth_check = AsyncMock(return_value={"status": "healthy"})
    await hb._send_one_heartbeat()
    assert hb.status == HubStatus.CONNECTED


@pytest.mark.asyncio
async def test_loop_starts_when_offline_and_self_heals(mock_connector):
    """Regression: a hub outage at boot must not permanently disable heartbeats.
    The loop starts even on OFFLINE, and a later good probe restores CONNECTED."""
    mock_connector.auth_check = AsyncMock(return_value={"error": "refused", "status": 0})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.OFFLINE
    assert hb.is_running  # loop runs despite the boot-time outage
    mock_connector.auth_check = AsyncMock(return_value={"status": "healthy"})
    await asyncio.sleep(1.5)
    assert hb.status == HubStatus.CONNECTED
    await hb.stop()


@pytest.mark.asyncio
async def test_loop_not_started_on_auth_failure(mock_connector):
    """A credential failure is a config error — do not spin a retry loop."""
    mock_connector.auth_check = AsyncMock(return_value={"error": "unauthorized", "status": 401})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.AUTH_FAILED
    assert not hb.is_running
    await hb.stop()


@pytest.mark.asyncio
async def test_connected_is_gated_on_the_authenticated_probe(mock_connector):
    """#6037 regression: an unauthenticated 200 must NEVER produce CONNECTED.

    The exact live failure: hub reachable (health 200) while every
    authenticated call 401s on a stale key. The heartbeat must consult ONLY
    auth_check — health_check reaching CONNECTED is the ten-week blind spot.
    """
    mock_connector.health_check = AsyncMock(return_value={"status": "healthy"})
    mock_connector.auth_check = AsyncMock(return_value={"error": "Unauthorized", "status": 401})
    hb = Heartbeat(connector=mock_connector, interval=1)
    await hb.start()
    assert hb.status == HubStatus.AUTH_FAILED
    mock_connector.health_check.assert_not_called()
    await hb.stop()
