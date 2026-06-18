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

    async def run_build(self, task, base="main", module=None, target="archie-code", target_file=None):
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


# ---- autonomous-scheduler prereqs: #4322 branch idempotency + dedup -----------


def test_branch_name_is_unique_per_call():
    from archie_engine.build_loop import _branch_name

    a = _branch_name("fix the thing")
    b = _branch_name("fix the thing")
    assert a != b  # #4322: same task → different branch (unique suffix) → no retry collision
    assert a.startswith("engine/fix-the-thing-")


def test_dedup_tracker_skip_and_expiry(tmp_path):
    from archie_engine.dedup_tracker import DedupTracker

    t = DedupTracker(tmp_path)
    assert not t.should_skip(42, 3600)   # never attempted
    t.record(42)
    assert t.should_skip(42, 3600)       # within cooldown
    assert not t.should_skip(42, 0)      # cooldown 0 → already expired
    assert not t.should_skip(None, 3600)  # no id → never skip
    # persists across instances (same data_dir)
    assert DedupTracker(tmp_path).should_skip(42, 3600)


class _StubEngineDedup:
    def __init__(self, conn, tracker, cooldown=3600):
        self.hub_connector = conn
        self.dedup_tracker = tracker

        class _Cfg:
            autopull_cooldown_sec = cooldown

        self.config = _Cfg()
        self.run_build_calls = []

    async def run_build(self, task, base="main", module=None, target="archie-code", target_file=None):
        self.run_build_calls.append({"module": module, "target": target})
        return {"success": True, "stage": "done", "pr_url": "x", "branch": "engine/x"}


async def test_pull_and_build_skips_attempted_issue(tmp_path):
    from archie_engine.dedup_tracker import DedupTracker

    tracker = DedupTracker(tmp_path)
    tracker.record(2)  # the high-severity fitness issue was already attempted
    conn = _Conn([
        {"id": 2, "file_path": "platform_v2/tools/fitness/routes.py", "severity": "high"},
        {"id": 3, "file_path": "platform_v2/tools/doc/routes.py", "severity": "low"},
    ])
    stub = _StubEngineDedup(conn, tracker)
    r = await Engine.pull_and_build(stub)
    assert len(stub.run_build_calls) == 1
    assert r.get("issue_id") == 3  # skipped attempted #2 (even though higher sev), rotated to #3
    assert tracker.should_skip(3, 3600)  # #3 now recorded (before the build)


# ---- fetch window (#380): in-scope findings rank low in the queue, so the engine
# must fetch a wide enough window or every cycle no-ops -------------------------------


def test_autopull_fetch_limit_default():
    from archie_engine.config import EngineConfig

    assert EngineConfig().autopull_fetch_limit == 200  # wide enough to reach low-ranked in-scope


class _LimitRecordingConn:
    """Records the limit pull_and_build asks for, returns one in-scope issue."""

    def __init__(self):
        self.captured_limit = None

    async def get_repair_issues(self, status="open", limit=100):
        self.captured_limit = limit
        return {"success": True, "issues": [
            {"id": 9, "file_path": "platform_v2/tools/doc/routes.py", "message": "m", "severity": "low"},
        ]}


class _StubEngineCfgLimit:
    def __init__(self, conn, fetch_limit=200):
        self.hub_connector = conn

        class _Cfg:
            autopull_fetch_limit = fetch_limit
            autopull_cooldown_sec = 21600

        self.config = _Cfg()
        self.run_build_calls = []

    async def run_build(self, task, base="main", module=None, target="archie-code", target_file=None):
        self.run_build_calls.append({"module": module, "target": target})
        return {"success": True, "stage": "done", "pr_url": "x", "branch": "engine/x"}


async def test_pull_and_build_uses_config_fetch_limit_when_unspecified():
    conn = _LimitRecordingConn()
    stub = _StubEngineCfgLimit(conn, fetch_limit=175)
    await Engine.pull_and_build(stub)  # no explicit limit
    assert conn.captured_limit == 175  # resolved from config, not the old 50/100 default
    assert len(stub.run_build_calls) == 1


async def test_pull_and_build_explicit_limit_overrides_config():
    conn = _LimitRecordingConn()
    stub = _StubEngineCfgLimit(conn, fetch_limit=200)
    await Engine.pull_and_build(stub, limit=33)
    assert conn.captured_limit == 33  # explicit caller wins
