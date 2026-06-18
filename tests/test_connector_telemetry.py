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

    async def fake_post(path, data=None, timeout=None):
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

    async def fake_post(path, data=None, timeout=None):
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

    async def fake_post(path, data=None, timeout=None):
        captured["path"] = path
        captured["data"] = data
        return {"success": True, "response": '[{"path":"archie_engine/x.py"}]'}

    c.post = fake_post
    out = await c.dhq_complete("plan this task")
    assert captured["path"] == "/api/internal/dhq/chat"  # the synchronous DHQ path, not direct Ollama
    assert captured["data"]["prompt"] == "plan this task"
    assert out == '[{"path":"archie_engine/x.py"}]'


async def test_dhq_complete_passes_capability_and_prefer_agent():
    """The build loop's plan step targets a CODER (#4256), not the cockpit voice."""
    c = _conn()
    captured = {}

    async def fake_post(path, data=None, timeout=None):
        captured["path"] = path
        captured["data"] = data
        captured["timeout"] = timeout
        return {"success": True, "response": "[]"}

    c.post = fake_post
    out = await c.dhq_complete(
        "plan this task",
        capability="code",
        prefer_agent="F.O.R.G.E.",
        module_id="archie_code_engine",
    )
    assert captured["path"] == "/api/internal/dhq/chat"
    assert captured["data"]["capability"] == "code"
    assert captured["data"]["prefer_agent"] == "F.O.R.G.E."
    assert captured["data"]["module_id"] == "archie_code_engine"
    # plan step must outlast F.O.R.G.E. inference — NOT the 10s control-plane default (#4256)
    assert captured["timeout"] is not None and captured["timeout"] > 10
    assert out == "[]"


async def test_dhq_complete_omits_agent_override_by_default():
    """No capability/prefer_agent → payload stays prompt-only (cockpit A.R.C.H.I.E. default)."""
    c = _conn()
    captured = {}

    async def fake_post(path, data=None, timeout=None):
        captured["data"] = data
        return {"success": True, "response": "ok"}

    c.post = fake_post
    await c.dhq_complete("hi")
    assert "capability" not in captured["data"]
    assert "prefer_agent" not in captured["data"]
    assert "module_id" not in captured["data"]


async def test_dhq_complete_empty_when_no_response():
    c = _conn()

    async def fake_post(path, data=None, timeout=None):
        return {"success": False}

    c.post = fake_post
    assert await c.dhq_complete("x") == ""


def test_resolve_timeout_wraps_int_and_passes_default_through():
    """aiohttp rejects a bare int session timeout; a per-call override must be wrapped."""
    import aiohttp
    from archie_engine.hub.connector import _resolve_timeout
    default = aiohttp.ClientTimeout(total=10)
    wrapped = _resolve_timeout(300, default)
    assert isinstance(wrapped, aiohttp.ClientTimeout)
    assert wrapped.total == 300
    assert _resolve_timeout(None, default) is default


# --- #4261 build-result reporting + #4262 reverify (wire-loop consume) ---------


async def test_report_build_result_posts_to_build_result_endpoint():
    c = _conn()
    captured = {}

    async def fake_post(path, data=None, timeout=None):
        captured["path"] = path
        captured["data"] = data
        return {"success": True, "run_id": 42}

    c.post = fake_post
    r = await c.report_build_result(
        task="t", branch="b", pr_url="u", status="completed",
        tests=[{"name": "pytest", "status": "pass"}],
    )
    assert captured["path"] == "/api/internal/engine/build-result"
    assert captured["data"]["task"] == "t"
    assert captured["data"]["tests"][0]["status"] == "pass"
    assert r["run_id"] == 42


async def test_code_health_reverify_with_and_without_module():
    c = _conn()
    seen = []

    async def fake_post(path, data=None, timeout=None):
        seen.append((path, data))
        return {"modules": 1, "fixed": 1, "still_open": 0, "details": []}

    c.post = fake_post
    await c.code_health_reverify("repair_bay")
    await c.code_health_reverify()
    assert seen[0][0] == "/api/internal/code-health/reverify"
    assert seen[0][1] == {"module": "repair_bay"}
    assert seen[1][1] == {}  # no module → empty body (re-audit everything deployed)


class _RecordingConnector:
    """Captures the post-run reporter calls without a live hub."""

    def __init__(self):
        self.calls = []

    async def log_job(self, **kw):
        self.calls.append(("log_job", kw))
        return {"ok": True}

    async def report_build_result(self, **kw):
        self.calls.append(("report_build_result", kw))
        return {"success": True, "run_id": 1}

    async def code_health_reverify(self, module=None):
        self.calls.append(("code_health_reverify", module))
        return {"modules": 1, "fixed": 1, "still_open": 0, "details": []}


def _names(conn):
    return [c[0] for c in conn.calls]


async def test_emit_telemetry_reports_and_reverifies_with_module():
    from archie_engine.build_loop import BuildLoop, BuildResult

    conn = _RecordingConnector()
    loop = BuildLoop(tools=None, dispatch_fn=None, connector=conn)
    r = BuildResult(task="fix bug", branch="engine/fix", success=True,
                    tests_passed=True, module="repair_bay", test_output="2 passed")
    await loop.emit_telemetry(r)
    names = _names(conn)
    assert "log_job" in names
    assert "report_build_result" in names
    assert "code_health_reverify" in names
    rbr = next(kw for n, kw in conn.calls if n == "report_build_result")
    assert rbr["status"] == "completed"
    assert rbr["tests"][0]["status"] == "pass"


async def test_emit_telemetry_skips_reverify_without_module():
    from archie_engine.build_loop import BuildLoop, BuildResult

    conn = _RecordingConnector()
    loop = BuildLoop(tools=None, dispatch_fn=None, connector=conn)
    r = BuildResult(task="self build", branch="engine/x", success=True, tests_passed=True)
    await loop.emit_telemetry(r)
    names = _names(conn)
    assert "report_build_result" in names
    assert "code_health_reverify" not in names  # no platform module → nothing to reverify


async def test_emit_telemetry_reports_failed_build_and_no_reverify():
    from archie_engine.build_loop import BuildLoop, BuildResult

    conn = _RecordingConnector()
    loop = BuildLoop(tools=None, dispatch_fn=None, connector=conn)
    r = BuildResult(task="broken", branch="engine/b", success=False,
                    tests_passed=False, module="repair_bay", test_output="1 failed")
    await loop.emit_telemetry(r)
    rbr = next(kw for n, kw in conn.calls if n == "report_build_result")
    assert rbr["status"] == "failed"
    assert rbr["tests"][0]["status"] == "fail"
    assert "code_health_reverify" not in _names(conn)  # red build never reverifies
