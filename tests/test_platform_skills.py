"""#5333 skill bridge -- the engine's proxy to the platform invokable-skills registry.

Hermetic: the transport seam (``_request``) is monkeypatched, so nothing here needs
a live hub. What is pinned is the behaviour that actually broke or could break:

  * every invocation is attributed to delegation_source='tui' -- the entire point of
    the slice. The platform hardcoded 'web_chat' until #5333, so a regression here
    silently mis-attributes every TUI action in task_execution_log and Token Economy.
  * the proxy is FAIL-SOFT. It runs inside the websocket handler; an exception drops
    the connection and takes the whole TUI down, so a dead hub must become a value.
  * the default hub is a MESH address, never a public hostname (60s CDN cap, bypasses
    the dispatch queue) and never a bare LAN IP from inside a container.
"""

import ast
import asyncio
import os
from pathlib import Path

import pytest

from archie_engine import platform_skills as ps


def _run(coro):
    """Run one coroutine on its OWN loop.

    ⚠️ Was `asyncio.get_event_loop().run_until_complete(coro)`, which relies on the
    IMPLICIT event loop. pytest-asyncio 1.4.0 stopped creating one, so these 10 tests
    raised "no current event loop" — and `pyproject.toml` carried a `<1.4` pin purely
    to keep the implicit loop alive. That pin made a clean install green only by
    freezing a dependency, while the engine container (which resolves differently)
    ran a RED suite. Since the build loop gates on a green `pytest`, that red suite
    meant no engine build could ever complete (#6027/#6038).

    `asyncio.run` creates and closes a fresh loop per call, which is what every one of
    these tests wants — each drives a single awaitable against a monkeypatched seam.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------- attribution


def test_invoke_stamps_the_tui_source(monkeypatch):
    seen = {}

    async def fake(method, path, payload=None):
        seen["method"], seen["path"], seen["payload"] = method, path, payload
        return {"task_id": 1, "status": "queued"}

    monkeypatch.setattr(ps, "_request", fake)
    out = _run(ps.invoke_platform_skill("health_check", "why"))

    assert out["task_id"] == 1
    assert seen["method"] == "POST"
    assert seen["path"] == "/api/internal/delegation/submit"
    # THE invariant of this slice.
    assert seen["payload"]["delegation_source"] == "tui"
    assert ps.DELEGATION_SOURCE == "tui"


def test_invoke_passes_capability_reason_args_through(monkeypatch):
    seen = {}

    async def fake(method, path, payload=None):
        seen.update(payload or {})
        return {"task_id": 2}

    monkeypatch.setattr(ps, "_request", fake)
    _run(ps.invoke_platform_skill("run_qa_suite", "  nightly  ", args={"suite_id": 3}, priority=8))
    assert seen["capability"] == "run_qa_suite"
    assert seen["reason"] == "nightly"  # stripped
    assert seen["args"] == {"suite_id": 3}
    assert seen["priority"] == 8


@pytest.mark.parametrize("cap,reason", [("", "r"), ("   ", "r"), ("health_check", ""), ("health_check", "  ")])
def test_invoke_refuses_empty_input_without_touching_the_hub(monkeypatch, cap, reason):
    called = []

    async def fake(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(ps, "_request", fake)
    out = _run(ps.invoke_platform_skill(cap, reason))
    assert "error" in out
    assert not called, "a client-side input bug must not cost a hub round-trip"


def test_capability_is_NOT_validated_locally(monkeypatch):
    """The hub owns the registry. A local allowlist would be a second source of
    truth that goes stale the moment a capability is added."""
    seen = {}

    async def fake(method, path, payload=None):
        seen.update(payload or {})
        return {"task_id": 9}

    monkeypatch.setattr(ps, "_request", fake)
    out = _run(ps.invoke_platform_skill("a_capability_added_next_week", "reason"))
    assert out["task_id"] == 9
    assert seen["capability"] == "a_capability_added_next_week"


# ---------------------------------------------------------------- fail-soft


def test_request_returns_an_error_value_when_the_hub_is_unreachable(monkeypatch):
    """No exception may escape: this runs inside the ws handler."""

    class Boom:
        def __call__(self, *a, **k):
            raise OSError("connection refused")

    import archie_engine.platform_skills as mod

    monkeypatch.setattr(mod, "hub_base", lambda: "http://127.0.0.1:1")  # nothing listening
    out = _run(mod._request("GET", "/api/internal/delegation/invokable-skills"))
    assert "error" in out and "hub unreachable" in out["error"]


def test_status_rejects_a_non_numeric_task_id(monkeypatch):
    called = []

    async def fake(*a, **k):
        called.append(1)
        return {}

    monkeypatch.setattr(ps, "_request", fake)
    for bad in ("abc", None, {}):
        out = _run(ps.platform_skill_status(bad))
        assert "error" in out
    assert not called


def test_status_builds_the_right_path(monkeypatch):
    seen = {}

    async def fake(method, path, payload=None):
        seen["method"], seen["path"] = method, path
        return {"status": "pending"}

    monkeypatch.setattr(ps, "_request", fake)
    out = _run(ps.platform_skill_status("77"))  # string coerces
    assert out["status"] == "pending"
    assert seen == {"method": "GET", "path": "/api/internal/delegation/77/status"}


# ---------------------------------------------------------------- transport rules


def test_hub_base_prefers_env_and_defaults_to_the_MESH_ip(monkeypatch):
    monkeypatch.setenv("ARCHIE_HUB_URL", "http://100.64.0.4:3000/")
    assert ps.hub_base() == "http://100.64.0.4:3000"  # trailing slash trimmed

    monkeypatch.delenv("ARCHIE_HUB_URL", raising=False)
    monkeypatch.setenv("ARCHIE_PLATFORM_URL", "http://100.64.0.4:3000")
    assert ps.hub_base() == "http://100.64.0.4:3000"

    monkeypatch.delenv("ARCHIE_PLATFORM_URL", raising=False)
    default = ps.hub_base()
    assert default.startswith("http://100.64."), "default must be a MESH address"
    assert "kytranempowerment.com" not in default, "a public hostname hits the 60s CDN cap"


def test_auth_header_accepts_either_key_name(monkeypatch):
    monkeypatch.delenv("ARCHIE_HUB_API_KEY", raising=False)
    monkeypatch.setenv("INTERNAL_API_KEY", "k1")
    assert ps._auth_headers()["Authorization"] == "Bearer k1"

    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("ARCHIE_HUB_API_KEY", "k2")
    assert ps._auth_headers()["Authorization"] == "Bearer k2"


# ---------------------------------------------------------------- ws wiring


def test_engine_routes_all_three_message_types():
    """Wired at the dispatch table -- an unrouted type returns 'Unknown message type'."""
    engine_py = Path(__file__).resolve().parent.parent / "archie_engine" / "engine.py"
    tree = ast.parse(engine_py.read_text())
    handler = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_message"
    )
    compared = {
        c.comparators[0].value
        for n in ast.walk(handler)
        if isinstance(n, ast.Compare) and n.comparators
        for c in [n]
        if isinstance(c.comparators[0], ast.Constant) and isinstance(c.comparators[0].value, str)
    }
    for t in ("platform_skills", "platform_skill_invoke", "platform_skill_status"):
        assert t in compared, f"handle_message does not route {t}"
    # must not collide with the engine's OWN local skill list
    assert "list_skills" in compared, "the local skill list must still be routed"
