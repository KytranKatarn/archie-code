import pytest
import pytest_asyncio
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest_asyncio.fixture
async def engine(tmp_path):
    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config)
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_engine_has_context_bridge(engine):
    assert engine.context_bridge is not None


@pytest.mark.asyncio
async def test_engine_has_escalation_detector(engine):
    assert engine.escalation_detector is not None


@pytest.mark.asyncio
async def test_engine_has_mcp_server(engine):
    assert engine.mcp_server is not None


@pytest.mark.asyncio
async def test_mcp_tool_count(engine):
    tools = engine.mcp_server.get_tool_definitions()
    assert len(tools) >= 3
