import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig
from pathlib import Path


@pytest_asyncio.fixture
async def engine(tmp_path):
    # Create a custom skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "hello.md").write_text("---\nname: hello\ndescription: Say hello\n---\nSay hello to the user.")

    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config, custom_skill_dirs=[skills_dir])
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_skill_list_via_websocket(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "list_skills"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "skills_list"
        names = [s["name"] for s in response["skills"]]
        assert "hello" in names
        assert "commit" in names  # Community skill


@pytest.mark.asyncio
async def test_slash_command_routes_to_skill(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "/hello",
        }))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert response["type"] == "response"
        assert "skill:hello" in response.get("intent", "")


@pytest.mark.asyncio
async def test_unknown_slash_falls_through(engine):
    """Unknown /command should fall through to normal intent parsing."""
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "/nonexistent_skill_xyz",
        }))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert response["type"] == "response"
        # Should NOT be skill:nonexistent — falls through to conversation
