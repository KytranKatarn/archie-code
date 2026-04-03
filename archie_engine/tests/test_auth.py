import pytest
from pathlib import Path
from archie_engine.hub.auth import HubAuth


@pytest.fixture
def auth(tmp_path):
    return HubAuth(key_file=tmp_path / ".archie_key")


def test_store_and_load_key(auth):
    auth.store_key("test-api-key-12345")
    loaded = auth.load_key()
    assert loaded == "test-api-key-12345"


def test_load_key_missing(auth):
    loaded = auth.load_key()
    assert loaded is None


def test_bearer_header(auth):
    auth.store_key("mykey")
    headers = auth.get_headers()
    assert headers["Authorization"] == "Bearer mykey"


def test_clear_key(auth):
    auth.store_key("mykey")
    auth.clear_key()
    assert auth.load_key() is None


def test_has_key(auth):
    assert not auth.has_key()
    auth.store_key("mykey")
    assert auth.has_key()


def test_store_and_load_node_key(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_key("test-node-api-key-123")
    assert auth.load_node_key() == "test-node-api-key-123"


def test_get_node_headers(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_key("node-key-abc")
    headers = auth.get_node_headers()
    assert headers["X-Node-API-Key"] == "node-key-abc"
    assert headers["Content-Type"] == "application/json"


def test_get_node_headers_no_key(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    headers = auth.get_node_headers()
    assert "X-Node-API-Key" not in headers


def test_store_node_id(tmp_path):
    from archie_engine.hub.auth import HubAuth
    auth = HubAuth(key_file=tmp_path / ".hub_key")
    auth.store_node_id("node_abc123")
    assert auth.load_node_id() == "node_abc123"
