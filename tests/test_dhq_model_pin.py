"""#380 Phase 3: the plan step pins a coding model via dhq_complete(model=) → the hub
passes it as model_override. Verifies the engine-side payload + the config default."""

from archie_engine.config import EngineConfig
from archie_engine.hub.auth import HubAuth
from archie_engine.hub.connector import HubConnector


def test_build_plan_model_defaults_to_coder():
    assert EngineConfig().build_plan_model == "qwen2.5-coder:7b"


def _conn(tmp_path):
    return HubConnector(hub_url="http://hub", auth=HubAuth(key_file=tmp_path / ".k"), timeout=5)


async def test_dhq_complete_sends_model_when_pinned(tmp_path):
    conn = _conn(tmp_path)
    captured = {}

    async def fake_post(path, data=None, timeout=None):
        captured["path"], captured["data"] = path, data
        return {"response": "ok"}

    conn.post = fake_post
    out = await conn.dhq_complete("plan this", capability="code",
                                  prefer_agent="F.O.R.G.E.", model="qwen2.5-coder:7b")
    assert out == "ok"
    assert captured["path"] == "/api/internal/dhq/chat"
    assert captured["data"]["model"] == "qwen2.5-coder:7b"
    assert captured["data"]["capability"] == "code"


async def test_dhq_complete_omits_model_when_unset(tmp_path):
    conn = _conn(tmp_path)
    captured = {}

    async def fake_post(path, data=None, timeout=None):
        captured["data"] = data
        return {"response": "ok"}

    conn.post = fake_post
    await conn.dhq_complete("just chat")  # cockpit default — no model pin
    assert "model" not in captured["data"]
