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
    # #380 Lane 3: PLATFORM_SCOPE was widened to platform-minus-kernel -- ai_bridge/
    # is now reachable (it was excluded under the old 19-path allowlist).
    assert is_in_scope("ai_bridge/agent_loop.py", PLATFORM_SCOPE)


def test_platform_scope_denies_core_secrets_and_excluded_modules():
    assert not is_in_scope("platform_v2/services/agent_service.py", PLATFORM_SCOPE)
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

    async def get_repair_issues(self, status="open", limit=100, auto_fixable=True, path_prefixes=None):
        if self._error:
            return {"error": "boom"}
        return {"success": True, "issues": self._i}


class _StubEngine:
    # #5004: the real Engine consults this before building. Stubs default to "never stale"
    # so these tests keep exercising SELECTION (scope, severity order, dedup) rather than
    # staleness; the staleness behaviour has its own tests below.
    stale_ids: set = set()

    def _finding_is_stale(self, task, file_path):
        return False

    async def _pull_proposal_build(self):
        # These tests exercise the ISSUES lane's no-op paths; the proposals
        # fall-through has its own suite (test_autopull_proposals.py).
        return None

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
    # #380 Lane 3: ai_bridge/ is now IN scope, so the kernel itself is the fixture
    # for "out of scope" -- it stays blocked under every PLATFORM_SCOPE revision.
    stub = _StubEngine(_Conn([{"id": 1, "file_path": "platform_v2/services/agent_service.py", "severity": "high"}]))
    r = await Engine.pull_and_build(stub)
    assert r["success"] is True and r.get("skipped") is True
    assert stub.run_build_calls == []  # governance-kernel finding filtered out


async def test_pull_and_build_picks_highest_severity_in_scope():
    stub = _StubEngine(_Conn([
        {"id": 1, "file_path": "platform_v2/services/agent_service.py", "severity": "critical"},  # out of scope (ignored)
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
    # #5004: the real Engine consults this before building. Stubs default to "never stale"
    # so these tests keep exercising SELECTION (scope, severity order, dedup) rather than
    # staleness; the staleness behaviour has its own tests below.
    stale_ids: set = set()

    def _finding_is_stale(self, task, file_path):
        return False

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

    async def get_repair_issues(self, status="open", limit=100, auto_fixable=True, path_prefixes=None):
        self.captured_limit = limit
        return {"success": True, "issues": [
            {"id": 9, "file_path": "platform_v2/tools/doc/routes.py", "message": "m", "severity": "low"},
        ]}


class _StubEngineCfgLimit:
    # #5004: see _StubEngine — never stale, so this stays a LIMIT test.
    def _finding_is_stale(self, task, file_path):
        return False

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


# --- #5004: skip findings that no longer reproduce -----------------------------------------
# Issue #7846 ("doc/routes.py line 178 exceeds 120 chars", created 2026-05-12) was picked on
# 2026-07-19 and burned a whole autonomous cycle discovering line 178 is now 49 chars.
# Autopull is 6-hourly and defers under GPU pressure, so a wasted pick costs 6-12h.


class _StubEngineStale(_StubEngine):
    """Marks specific issue ids stale, so we can assert the loop walks PAST them."""

    def __init__(self, conn, stale_ids):
        super().__init__(conn)
        self._stale = set(stale_ids)
        self.checked = []

    def _finding_is_stale(self, task, file_path):
        # id isn't passed to the real helper either — key off the task text like it does.
        self.checked.append(file_path)
        return any(f"line {i})" in task for i in self._stale)


_FP = "platform_v2/tools/doc/routes.py"

async def test_stale_issue_is_skipped_and_next_one_is_built():
    """The top-severity issue is stale -> the loop must build the NEXT one, not give up."""
    conn = _Conn([
        {"id": 7846, "file_path": _FP, "severity": "high", "message": "m", "line_number": 178},
        {"id": 7844, "file_path": _FP, "severity": "low", "message": "m", "line_number": 56},
    ])
    stub = _StubEngineStale(conn, stale_ids={178})
    r = await Engine.pull_and_build(stub)
    assert r["success"] is True
    assert r["issue_id"] == 7844, "must fall through to the non-stale issue"
    assert r["stale_skipped"] == [7846]
    assert len(stub.run_build_calls) == 1, "exactly one build, for the live finding"


async def test_all_stale_is_a_noop_not_a_build():
    """Every candidate stale -> no build at all, reported honestly."""
    conn = _Conn([
        {"id": 7846, "file_path": _FP, "severity": "high", "message": "m", "line_number": 178},
    ])
    stub = _StubEngineStale(conn, stale_ids={178})
    r = await Engine.pull_and_build(stub)
    assert r["success"] is True and r["skipped"] is True
    assert r["reason"] == "all in-scope issues stale"
    assert r["stale_skipped"] == [7846]
    assert stub.run_build_calls == [], "a stale queue must cost ZERO builds"


async def test_live_finding_is_untouched_by_the_skip():
    """No stale ids -> behaviour identical to before #5004 (no silent skipping of real work)."""
    conn = _Conn([{"id": 7844, "file_path": _FP, "severity": "low", "message": "m", "line_number": 56}])
    stub = _StubEngineStale(conn, stale_ids=set())
    r = await Engine.pull_and_build(stub)
    assert r["issue_id"] == 7844
    assert "stale_skipped" not in r
    assert len(stub.run_build_calls) == 1
