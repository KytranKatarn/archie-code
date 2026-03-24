import pytest


@pytest.fixture
def engine_config(tmp_path):
    """Config pointing to temp directory."""
    from archie_engine.config import EngineConfig
    return EngineConfig(data_dir=tmp_path)
