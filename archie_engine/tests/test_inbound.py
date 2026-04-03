"""Tests for inbound HTTP server that accepts hub-dispatched work."""

import pytest
from unittest.mock import AsyncMock
from aiohttp.test_utils import TestClient, TestServer
from archie_engine.hub.inbound import InboundServer


@pytest.fixture
def mock_job_handler():
    handler = AsyncMock()
    handler.return_value = {
        "success": True,
        "response": "Task completed successfully",
        "agent": "ARCHIE",
    }
    return handler


@pytest.fixture
async def inbound_client(mock_job_handler):
    server = InboundServer(host="127.0.0.1", port=0, node_api_key="test-key-123")
    server.set_job_handler(mock_job_handler)
    app = server._build_app()
    async with TestClient(TestServer(app)) as client:
        yield client, mock_job_handler


@pytest.mark.asyncio
async def test_dispatch_job_success(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "Review this code for security issues",
        "context": {"files": ["main.py"]},
    }, headers={"X-Node-API-Key": "test-key-123"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert "response" in data
    handler.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_rejects_bad_auth(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "Do something",
    }, headers={"X-Node-API-Key": "wrong-key"})
    assert resp.status == 401
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_rejects_no_auth(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={"task": "Do something"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_dispatch_rejects_empty_task(inbound_client):
    client, handler = inbound_client
    resp = await client.post("/api/dispatch", json={
        "task": "",
    }, headers={"X-Node-API-Key": "test-key-123"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_health_endpoint(inbound_client):
    client, _ = inbound_client
    resp = await client.get("/api/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert "engine_version" in data
