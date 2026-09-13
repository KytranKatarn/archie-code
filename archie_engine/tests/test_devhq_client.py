"""Dev HQ client for archie-tui: request shapes + the engine call sites.

The engine could previously only CREATE Dev HQ rows as a side effect of delegating —
write-only and blind. These pin the client's request shapes and, critically, that the
websocket dispatch actually reaches them: a client nothing calls changes nothing.

Async tests use @pytest.mark.asyncio deliberately. asyncio.run() clears the thread's
current event loop when it returns, which previously broke unrelated tests in this
suite. Patching is confined to a module attribute (devhq._request) — never a stdlib
function, which would be global for the test's duration.
"""

import os
import re

import pytest

from archie_engine import devhq

_ENGINE_SRC = os.path.join(os.path.dirname(__file__), "..", "engine.py")


@pytest.fixture
def calls(monkeypatch):
    """Capture (method, path, payload) instead of hitting the hub."""
    seen = []

    async def _fake(method, path, payload=None):
        seen.append((method, path, payload))
        return {"success": True}

    monkeypatch.setattr(devhq, "_request", _fake)
    return seen


class TestQueryString:
    def test_empty_params_produce_no_query_string(self):
        assert devhq._qs(status=None, limit=None) == ""

    def test_none_and_blank_are_dropped_but_zero_is_kept(self):
        """0 is a legitimate value (e.g. min_priority=0); only None/'' are absent."""
        qs = devhq._qs(a=None, b="", c=0, d="x")
        assert "a=" not in qs and "b=" not in qs
        assert "c=0" in qs and "d=x" in qs

    def test_values_are_url_encoded(self):
        assert "q=a+b" in devhq._qs(q="a b") or "q=a%20b" in devhq._qs(q="a b")


class TestReads:
    @pytest.mark.asyncio
    async def test_list_projects_is_a_get(self, calls):
        await devhq.list_projects()
        method, path, payload = calls[0]
        assert method == "GET" and path.startswith("/api/internal/projects")
        assert payload is None

    @pytest.mark.asyncio
    async def test_list_tasks_passes_filters_through(self, calls):
        await devhq.list_tasks(project_id=7, status="open", q="drain", limit=5)
        _, path, _ = calls[0]
        assert "project_id=7" in path and "status=open" in path and "limit=5" in path
        assert "q=drain" in path

    @pytest.mark.asyncio
    async def test_get_task_targets_the_id(self, calls):
        await devhq.get_task(6749)
        method, path, _ = calls[0]
        assert method == "GET" and path == "/api/internal/tasks/6749"


class TestWrites:
    @pytest.mark.asyncio
    async def test_create_task_posts_the_documented_body(self, calls):
        await devhq.create_task(project_id=3, title="t", description="d", priority=9)
        method, path, payload = calls[0]
        assert method == "POST" and path == "/api/internal/tasks"
        assert payload == {"project_id": 3, "title": "t", "description": "d", "priority": 9}

    @pytest.mark.asyncio
    async def test_priority_default_is_an_integer(self, calls):
        """unified_tasks.priority is INTEGER 1-10 — a word here is a 500 at the hub."""
        await devhq.create_task(project_id=1, title="t")
        assert isinstance(calls[0][2]["priority"], int)

    @pytest.mark.asyncio
    async def test_set_status_targets_the_status_route(self, calls):
        await devhq.set_task_status(42, "completed")
        method, path, payload = calls[0]
        assert method == "POST" and path == "/api/internal/tasks/42/status"
        assert payload == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_add_note_targets_the_note_route(self, calls):
        await devhq.add_task_note(42, "done")
        _, path, payload = calls[0]
        assert path == "/api/internal/tasks/42/note" and payload == {"note": "done"}


class TestFailSoft:
    @pytest.mark.asyncio
    async def test_a_hub_error_is_returned_not_raised(self, monkeypatch):
        """A hub outage must degrade the TUI, never drop the websocket."""

        async def _boom(method, path, payload=None):
            return {"error": "hub 403", "detail": "scope_denied"}

        monkeypatch.setattr(devhq, "_request", _boom)
        out = await devhq.list_tasks()
        assert out["error"] == "hub 403"


class TestEngineCallSites:
    """A client nothing calls fixes nothing — this is the half that was missing before."""

    def _src(self):
        with open(_ENGINE_SRC) as fh:
            return fh.read()

    @pytest.mark.parametrize(
        "msg_type,fn",
        [
            ("devhq_projects", "list_projects"),
            ("devhq_tasks", "list_tasks"),
            ("devhq_task", "get_task"),
            ("devhq_task_create", "create_task"),
            ("devhq_task_status", "set_task_status"),
            ("devhq_task_note", "add_task_note"),
        ],
    )
    def test_websocket_dispatch_handles_each_message(self, msg_type, fn):
        src = self._src()
        assert re.search(r'msg_type == "%s"' % msg_type, src), msg_type
        assert fn in src, "%s handled but %s never called" % (msg_type, fn)
