import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from archie_engine.inference import InferenceClient


@pytest.fixture
def client():
    return InferenceClient(ollama_host="http://localhost:11434")


def _mock_response(status=200, json_data=None):
    """Create a mock aiohttp response that works as async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


@pytest.mark.asyncio
async def test_generate_returns_response(client):
    mock_resp = _mock_response(200, {
        "response": "Hello! How can I help?",
        "model": "qwen2.5:7b",
        "done": True,
    })
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.generate(prompt="hello", model="qwen2.5:7b")
    assert result["response"] == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_chat_returns_message(client):
    mock_resp = _mock_response(200, {
        "message": {"role": "assistant", "content": "Hi there!"},
        "model": "qwen2.5:7b",
        "done": True,
    })
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.chat(
            messages=[{"role": "user", "content": "hello"}],
            model="qwen2.5:7b",
        )
    assert result["message"]["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_list_models(client):
    mock_resp = _mock_response(200, {
        "models": [{"name": "qwen2.5:7b"}, {"name": "llama3.2:3b"}]
    })
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        models = await client.list_models()
    assert len(models) == 2


@pytest.mark.asyncio
async def test_connection_error_handled(client):
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Connection refused")):
        result = await client.generate(prompt="test", model="test")
    assert "error" in result


@pytest.mark.asyncio
async def test_is_available_true(client):
    mock_resp = _mock_response(200, {"models": []})
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        assert await client.is_available() is True


@pytest.mark.asyncio
async def test_is_available_false(client):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("refused")):
        assert await client.is_available() is False


@pytest.mark.asyncio
async def test_warm_model_success(client):
    mock_resp = _mock_response(200, {"response": "", "done": True})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.warm_model("qwen2.5:7b")
    assert result is True


@pytest.mark.asyncio
async def test_warm_model_failure(client):
    with patch("aiohttp.ClientSession.post", side_effect=Exception("refused")):
        result = await client.warm_model("qwen2.5:7b")
    assert result is False


@pytest.mark.asyncio
async def test_generate_with_system_prompt(client):
    mock_resp = _mock_response(200, {"response": "I am ARCHIE.", "done": True})
    with patch("aiohttp.ClientSession.post", return_value=mock_resp):
        result = await client.generate(
            prompt="Who are you?",
            model="qwen2.5:7b",
            system="You are ARCHIE.",
        )
    assert result["response"] == "I am ARCHIE."


@pytest.mark.asyncio
async def test_list_models_connection_error(client):
    with patch("aiohttp.ClientSession.get", side_effect=Exception("refused")):
        models = await client.list_models()
    assert models == []
