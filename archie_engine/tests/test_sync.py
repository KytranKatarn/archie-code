import pytest
import pytest_asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
from archie_engine.hub.sync import HubSync


@pytest.fixture
def mock_connector():
    conn = AsyncMock()
    conn.get_skills = AsyncMock(return_value={
        "skills": [
            {"name": "commit", "content": "# Commit skill\nCreate commits.", "version": "1.0"},
            {"name": "review", "content": "# Review skill\nReview PRs.", "version": "1.0"},
        ]
    })
    conn.get_model_state = AsyncMock(return_value={
        "models": [{"name": "qwen2.5:7b", "loaded": True}, {"name": "llama3:8b", "loaded": False}]
    })
    conn.list_agents = AsyncMock(return_value={
        "agents": [{"name": "ARCHIE", "station": "COMMAND", "shift_state": "active"}]
    })
    return conn


@pytest.fixture
def sync(mock_connector, tmp_path):
    return HubSync(connector=mock_connector, cache_dir=tmp_path / "cache")


@pytest.mark.asyncio
async def test_sync_skills_downloads(sync, tmp_path):
    await sync.sync_skills()
    skills_dir = tmp_path / "cache" / "skills"
    assert skills_dir.exists()
    assert (skills_dir / "commit.md").exists()
    assert (skills_dir / "review.md").exists()


@pytest.mark.asyncio
async def test_sync_skills_content(sync, tmp_path):
    await sync.sync_skills()
    content = (tmp_path / "cache" / "skills" / "commit.md").read_text()
    assert "Commit skill" in content


@pytest.mark.asyncio
async def test_get_cached_skills(sync):
    await sync.sync_skills()
    skills = sync.get_cached_skills()
    assert len(skills) == 2
    assert any(s["name"] == "commit" for s in skills)


@pytest.mark.asyncio
async def test_sync_agents(sync):
    await sync.sync_agents()
    agents = sync.get_cached_agents()
    assert len(agents) == 1
    assert agents[0]["name"] == "ARCHIE"


@pytest.mark.asyncio
async def test_sync_models(sync):
    await sync.sync_models()
    models = sync.get_cached_models()
    assert len(models) == 2


@pytest.mark.asyncio
async def test_sync_all(sync):
    await sync.sync_all()
    assert len(sync.get_cached_skills()) == 2
    assert len(sync.get_cached_agents()) == 1
    assert len(sync.get_cached_models()) == 2


@pytest.mark.asyncio
async def test_get_best_agent(sync):
    await sync.sync_agents()
    agent = sync.get_best_agent(intent_type="code_task")
    assert agent is not None
    assert agent["name"] == "ARCHIE"


@pytest.mark.asyncio
async def test_get_loaded_models(sync):
    await sync.sync_models()
    loaded = sync.get_loaded_models()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_offline_returns_cached(sync):
    await sync.sync_all()
    sync.connector.get_skills = AsyncMock(side_effect=Exception("offline"))
    assert len(sync.get_cached_skills()) == 2
    assert len(sync.get_cached_agents()) == 1
