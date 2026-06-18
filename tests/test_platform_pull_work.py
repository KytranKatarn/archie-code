"""Tests for the engine->platform pull-work expansion (#380).

Covers PLATFORM_SCOPE allow/deny, the issue->task helper, and pull_and_build's
scope filtering + target routing. pull_and_build sources the ISSUES queue (the
per-file findings that carry a file_path). No live hub/GitHub — pull_and_build is
exercised against a stub engine with a fake connector + a recording run_build.
"""

from archie_engine.engine import Engine, _format_issue_task, _module_from_path
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


def test_format_issue_task_includes_file_and_message():
    t = _format_issue_task(
        {"message": "unused import", "suggestion": "remove it", "severity": "low", "line_number": 12},
        "platform_v2/tools/doc/routes.py",
    )
    assert "platform_v2/tools/doc/routes.py" in t
    assert "line 12" in t
    assert "unused import" in t
    assert "remove it" in t


# ---- pull_and_build (stub engine; no live hub/GitHub) ------------------------


class _Conn:
    def __init__(self, issues, error=False):
        self._i = issues
        self._error = error

    async def get_repair_issues(self, status="open", limit=100):
        if self._error:
            return {"error": "boom"}
        return {"success": True, "issues": self._i}


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
    stub = _StubEngine(_Conn([{"id": 1, "file_path": "ai_bridge/agent_loop.py", "severity": "high"}]))
    r = await Engine.pull_and_build(stub)
    assert r["success"] is True and r.get("skipped") is True
    assert stub.run_build_calls == []  # core-platform finding filtered out


async def test_pull_and_build_picks_highest_severity_in_scope():
    stub = _StubEngine(_Conn([
        {"id": 1, "file_path": "ai_bridge/x.py", "severity": "critical"},  # out of scope (ignored)
        {"id": 2, "file_path": "platform_v2/tools/fitness/routes.py", "message": "m", "severity": "low"},
        {"id": 3, "file_path": "platform_v2/tools/doc/routes.py", "message": "m", "severity": "high"},
    ]))
    r = await Engine.pull_and_build(stub)
    assert len(stub.run_build_calls) == 1
    call = stub.run_build_calls[0]
    assert call["target"] == "archie-platform"
    assert call["module"] == "doc"  # highest-severity IN-SCOPE wins (high > low)
    assert r.get("issue_id") == 3


async def test_run_build_rejects_unknown_target():
    # validation runs before any self access → a bare object() is a fine stub
    r = await Engine.run_build(object(), "do something", target="bogus")
    assert r["success"] is False
    assert "unknown build target" in r["error"]
