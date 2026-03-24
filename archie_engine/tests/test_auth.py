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
