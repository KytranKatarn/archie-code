import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.auth import HubAuth


def _mock_response(status=200, json_data=None):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


@pytest.fixture
def connector(tmp_path):
    auth = HubAuth(key_file=tmp_path / ".key")
    auth.store_key("test-key")
    return HubConnector(hub_url="http://localhost:3000", auth=auth, timeout=5)


@pytest.mark.asyncio
async def test_get_success(connector):
    mock_resp = _mock_response(200, {"status": "ok"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_post_success(connector):
    mock_resp = _mock_response(200, {"result": "done"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.post("/api/action", data={"key": "val"})
    assert result["result"] == "done"


@pytest.mark.asyncio
async def test_auth_failure_returns_error(connector):
    mock_resp = _mock_response(401, {"error": "unauthorized"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 401


@pytest.mark.asyncio
async def test_connection_error_returns_error(connector):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 0


@pytest.mark.asyncio
async def test_server_error_returns_error(connector):
    mock_resp = _mock_response(500, {"error": "internal"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get("/api/health")
    assert "error" in result
    assert result["status"] == 500


@pytest.mark.asyncio
async def test_register_node(connector):
    mock_resp = _mock_response(200, {"node_id": "abc-123", "status": "registered"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.register_node(hostname="my-machine", gpu_model="RTX 3070", ram_gb=32)
    assert result.get("node_id") == "abc-123"


@pytest.mark.asyncio
async def test_health_check(connector):
    mock_resp = _mock_response(200, {"status": "ok", "version": "5.32.0"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.health_check()
    assert result.get("status") == "ok"


@pytest.mark.asyncio
async def test_search_knowledge(connector):
    mock_resp = _mock_response(200, {"results": [{"content": "test"}]})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.search_knowledge("auth middleware")
    assert len(result.get("results", [])) > 0


@pytest.mark.asyncio
async def test_dispatch(connector):
    mock_resp = _mock_response(200, {"response": "Here's the fix", "agent_used": "ARCHIE"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await connector.dispatch(prompt="fix the bug", model="qwen2.5:7b", agent_target="ARCHIE")
    assert "response" in result


@pytest.mark.asyncio
async def test_list_agents(connector):
    mock_resp = _mock_response(200, {"agents": [{"name": "ARCHIE"}]})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.list_agents()
    assert len(result.get("agents", [])) > 0


@pytest.mark.asyncio
async def test_get_skills(connector):
    mock_resp = _mock_response(200, {"skills": [{"name": "commit"}]})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        result = await connector.get_skills()
    assert len(result.get("skills", [])) > 0
