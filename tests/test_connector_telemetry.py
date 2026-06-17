"""Tests for HubConnector.log_job → engine build telemetry endpoint (#4257)."""

from archie_engine.hub.connector import HubConnector


class _FakeAuth:
    def get_headers(self):
        return {"Authorization": "Bearer x"}


def _conn():
    return HubConnector(hub_url="http://hub", auth=_FakeAuth())


async def test_log_job_posts_to_engine_telemetry_endpoint():
    c = _conn()
    calls = []

    async def fake_post(path, data=None):
        calls.append((path, data))
        return {"ok": True, "id": 7}

    c.post = fake_post
    r = await c.log_job(
        task="build feature X", agent_name="A.R.C.H.I.E. Engine",
        result_summary="done", duration_ms=1200,
        success=True, model="qwen2.5:7b",
        prompt_tokens=10, completion_tokens=5,
        files_changed=["archie_engine/x.py"], branch="feat/x",
    )
    assert r.get("ok")
    assert len(calls) == 1
    path, data = calls[0]
    # repointed away from the dead /api/archie/jobs
    assert path == "/api/internal/engine/telemetry"
    assert data["task"] == "build feature X"
    assert data["success"] is True
    assert data["model"] == "qwen2.5:7b"
    assert data["files_changed"] == ["archie_engine/x.py"]
    assert data["branch"] == "feat/x"


async def test_log_job_backward_compatible_with_original_4_args():
    # the existing handle_inbound_job caller passes only the original 4 args
    c = _conn()
    captured = {}

    async def fake_post(path, data=None):
        captured["path"] = path
        captured["data"] = data
        return {"ok": True}

    c.post = fake_post
    await c.log_job("t", "agent", "summary", 0)
    assert captured["path"] == "/api/internal/engine/telemetry"
    assert captured["data"]["success"] is True  # default applied
    assert captured["data"]["prompt_tokens"] == 0


async def test_dhq_complete_posts_to_dhq_chat_and_returns_reply():
    c = _conn()
    captured = {}

    async def fake_post(path, data=None):
        captured["path"] = path
        captured["data"] = data
        return {"success": True, "response": '[{"path":"archie_engine/x.py"}]'}

    c.post = fake_post
    out = await c.dhq_complete("plan this task")
    assert captured["path"] == "/api/internal/dhq/chat"  # the synchronous DHQ path, not direct Ollama
    assert captured["data"]["prompt"] == "plan this task"
    assert out == '[{"path":"archie_engine/x.py"}]'


async def test_dhq_complete_empty_when_no_response():
    c = _conn()

    async def fake_post(path, data=None):
        return {"success": False}

    c.post = fake_post
    assert await c.dhq_complete("x") == ""
