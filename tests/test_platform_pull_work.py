"""Tests for the engine->platform pull-work expansion (#380).

Covers PLATFORM_SCOPE allow/deny, the proposal->task helpers, and pull_and_build's
scope filtering + target routing (no live hub/GitHub — pull_and_build is exercised
against a stub engine with a fake connector + recording run_build).
"""

from archie_engine.engine import (
    Engine,
    _format_proposal_task,
    _module_from_path,
    _proposal_path,
)
from archie_engine.scope_guard import PLATFORM_SCOPE, is_in_scope


def test_platform_scope_allows_app_modules():
    assert is_in_scope("platform_v2/tools/fitness/routes.py", PLATFORM_SCOPE)
    assert is_in_scope("platform_v2/tools/doc/services/x.py", PLATFORM_SCOPE)
    assert is_in_scope("platform_v2/tests/test_x.py", PLATFORM_SCOPE)


def test_platform_scope_denies_core_secrets_and_excluded_modules():
    assert not is_in_scope("platform_v2/services/agent_service.py", PLATFORM_SCOPE)
    assert not is_in_scope("ai_bridge/agent_loop.py", PLATFORM_SCOPE)
    # media_studio/game_studio/media_hub are deliberately EXCLUDED (real prod data)
    assert not is_in_scope("platform_v2/tools/media_studio/routes.py", PLATFORM_SCOPE)
    # blocked globs always win, even under an allowed dir
    assert not is_in_scope("platform_v2/tools/fitness/.env", PLATFORM_SCOPE)
    assert not is_in_scope("tools/department_hq/services/department_dispatcher.py", PLATFORM_SCOPE)


def test_module_from_path():
    assert _module_from_path("platform_v2/tools/fitness/routes.py") == "fitness"
    assert _module_from_path("ai_bridge/x.py") is None
    assert _module_from_path("") is None


def test_proposal_path_from_column_or_metadata():
    assert _proposal_path({"file_path": "a/b.py"}) == "a/b.py"
    assert _proposal_path({"metadata": {"file_path": "c/d.py"}}) == "c/d.py"
    assert _proposal_path({}) == ""
    assert _proposal_path("not a dict") == ""


def test_format_proposal_task_includes_file_and_title():
    t = _format_proposal_task({"title": "Fix X", "description": "details here"},
                              "platform_v2/tools/doc/routes.py")
    assert "platform_v2/tools/doc/routes.py" in t
    assert "Fix X" in t
    assert "details here" in t


# ---- pull_and_build (stub engine; no live hub/GitHub) ------------------------


class _Conn:
    def __init__(self, proposals, error=False):
        self._p = proposals
        self._error = error

    async def get_repair_proposals(self, status="proposed"):
        if self._error:
            return {"error": "boom"}
        return {"success": True, "proposals": self._p, "count": len(self._p)}


class _StubEngine:
    def __init__(self, conn):
        self.hub_connector = conn
        self.run_build_calls = []

    async def run_build(self, task, base="main", module=None, target="archie-code"):
        self.run_build_calls.append({"task": task, "module": module, "target": target})
        return {"success": True, "stage": "done", "pr_url": "x", "branch": "engine/x"}


async def test_pull_and_build_no_connector():
    r = await Engine.pull_and_build(_StubEngine(None))
    assert r["success"] is False


async def test_pull_and_build_queue_error():
    r = await Engine.pull_and_build(_StubEngine(_Conn([], error=True)))
    assert r["success"] is False


async def test_pull_and_build_noop_when_all_out_of_scope():
    stub = _StubEngine(_Conn([{"id": 1, "file_path": "ai_bridge/agent_loop.py", "priority": 5}]))
    r = await Engine.pull_and_build(stub)
    assert r["success"] is True and r.get("skipped") is True
    assert stub.run_build_calls == []  # nothing built — core-platform item filtered out


async def test_pull_and_build_picks_highest_priority_in_scope():
    stub = _StubEngine(_Conn([
        {"id": 1, "file_path": "ai_bridge/x.py", "priority": 9},  # out of scope (ignored despite high pri)
        {"id": 2, "file_path": "platform_v2/tools/fitness/routes.py", "title": "Fix fitness", "priority": 3},
        {"id": 3, "file_path": "platform_v2/tools/doc/routes.py", "title": "Fix doc", "priority": 7},
    ]))
    r = await Engine.pull_and_build(stub)
    assert len(stub.run_build_calls) == 1
    call = stub.run_build_calls[0]
    assert call["target"] == "archie-platform"
    assert call["module"] == "doc"  # highest-priority IN-SCOPE wins (7 > 3)
    assert r.get("proposal_id") == 3
