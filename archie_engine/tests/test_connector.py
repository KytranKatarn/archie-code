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


@pytest.mark.asyncio
async def test_log_job(connector):
    mock_resp = _mock_response(200, {"id": 42, "status": "logged"})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp) as mock_post:
        result = await connector.log_job(
            task="summarize document",
            agent_name="ARCHIE",
            result_summary="Document summarized in 3 bullet points.",
            duration_ms=1234,
        )
    assert result.get("status") == "logged"
    call_kwargs = mock_post.call_args
    sent_json = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
    if sent_json is None:
        sent_json = call_kwargs.kwargs.get("json")
    # Verify URL contains the expected path
    called_url = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("url", "")
    assert "/api/archie/jobs" in called_url


@pytest.mark.asyncio
async def test_get_agent_status(connector):
    mock_resp = _mock_response(200, {"agent_id": 7, "shift_state": "active", "station": "COMMAND"})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp) as mock_get:
        result = await connector.get_agent_status(7)
    assert result.get("shift_state") == "active"
    called_url = mock_get.call_args.args[0] if mock_get.call_args.args else mock_get.call_args.kwargs.get("url", "")
    assert "/api/starbase/agents/7/status" in called_url


@pytest.mark.asyncio
async def test_get_personality(connector):
    personality_data = {
        "agent_id": 1,
        "name": "archie",
        "pronouns": "she/her",
        "personality_traits": {"caring": 0.9, "empathetic": 0.92},
        "mood": {"current": "focused", "intensity": 0.5},
        "relationship": {"strength": 0.99},
    }
    mock_resp = _mock_response(200, personality_data)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp) as mock_get:
        result = await connector.get_personality(agent_id=1)
    assert result.get("name") == "archie"
    assert result.get("mood", {}).get("current") == "focused"
    called_url = mock_get.call_args.args[0] if mock_get.call_args.args else ""
    assert "/api/bridge/agent-personality/1" in called_url


@pytest.mark.asyncio
async def test_get_personality_hub_down(connector):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Connection refused")):
        result = await connector.get_personality(agent_id=1)
    assert "error" in result
