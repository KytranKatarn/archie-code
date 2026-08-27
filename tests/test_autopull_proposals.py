"""Proposals lane of pull_and_build (spec 2026-08-26 Phase 3).

When the ISSUES queue yields nothing buildable, the engine pulls fix_requested
Repair Bay proposals -- the class whose FIND/REPLACE fix-gen failed or whose
earlier PR closed unmerged. These pin: the task formatter, the eligibility
filter (source, excluded classes #4990, in-flight pr_number, scope, dedup),
record-before-build rotation, the record_proposal_pr convergence call, and
that BOTH no-op branches of pull_and_build fall through to this lane.
No live hub/GitHub -- a stub engine with a fake connector + recording run_build.
"""

import inspect

from archie_engine.engine import Engine, _format_proposal_task


def _prop(pid, fp, code="F401", status="fix_requested", **md_extra):
    md = {"source": "code_health_audit", "issue_code": code, "file_path": fp}
    md.update(md_extra)
    return {"id": pid, "title": f"finding {pid}", "description": "detail text",
            "status": status, "metadata": md}


def test_format_proposal_task_carries_file_code_and_finding():
    t = _format_proposal_task(_prop(7, "platform_v2/tools/doc/routes.py"),
                              "platform_v2/tools/doc/routes.py")
    assert "platform_v2/tools/doc/routes.py" in t
    assert "F401" in t
    assert "finding 7" in t
    assert "detail text" in t
    assert "only edit this file" in t


def test_format_proposal_task_truncates_and_survives_bad_metadata():
    p = _prop(8, "x.py")
    p["description"] = "z" * 5000
    p["metadata"] = "not-a-dict"
    t = _format_proposal_task(p, "x.py")
    assert len(t) < 2000
    assert "..." in t


# ---- the lane itself (stub engine) ------------------------------------------


class _Tracker:
    def __init__(self, skip=()):
        self.skip = set(skip)
        self.recorded = []

    def should_skip(self, key, cooldown):
        return key in self.skip

    def record(self, key):
        self.recorded.append(key)


class _Conn:
    def __init__(self, proposals, error=False, record_fails=False):
        self._p = proposals
        self._error = error
        self._record_fails = record_fails
        self.recorded_prs = []

    async def get_repair_proposals(self, status="fix_requested", limit=50):
        if self._error:
            return {"error": "boom"}
        return {"success": True, "proposals": self._p}

    async def record_proposal_pr(self, proposal_id, pr_number, pr_url=None, branch=None):
        if self._record_fails:
            raise RuntimeError("hub down")
        self.recorded_prs.append((proposal_id, pr_number))
        return {"success": True, "proposal_id": proposal_id, "status": "pr_open"}


class _StubEngine:
    _pull_proposal_build = Engine._pull_proposal_build

    def __init__(self, conn, tracker=None, build_result=None):
        self.hub_connector = conn
        self.dedup_tracker = tracker
        self.run_build_calls = []
        self._build_result = build_result or {
            "success": True, "stage": "done",
            "pr_number": 99, "pr_url": "u", "branch": "engine/x",
        }

    def _finding_is_stale(self, task, file_path):
        return False

    async def run_build(self, task, base="main", module=None, target="archie-code", target_file=None):
        self.run_build_calls.append({"task": task, "module": module,
                                     "target": target, "target_file": target_file})
        return dict(self._build_result)


IN_SCOPE = "platform_v2/tools/doc/routes.py"


async def test_builds_first_eligible_and_records_pr_on_proposal():
    conn = _Conn([_prop(11, IN_SCOPE)])
    e = _StubEngine(conn, _Tracker())
    r = await e._pull_proposal_build()
    assert r is not None and r["proposal_id"] == 11
    assert e.run_build_calls[0]["target"] == "archie-platform"
    assert e.run_build_calls[0]["target_file"] == IN_SCOPE
    assert conn.recorded_prs == [(11, 99)]
    assert r["proposal_recorded"] is True
    # record-BEFORE-build rotation: the dedup key is stamped even on later failure
    assert e.dedup_tracker.recorded == ["proposal:11"]


async def test_eligibility_filter_rejects_each_disqualifier():
    props = [
        _prop(1, IN_SCOPE, code="SQL_INJECTION_RISK"),         # excluded class (#4990)
        _prop(2, IN_SCOPE, code="LARGE_FILE"),                 # excluded class (#4990)
        _prop(3, IN_SCOPE, pr_number=123),                     # already in flight
        _prop(4, "platform_v2/services/agent_service.py"),     # out of scope
        _prop(5, IN_SCOPE),                                    # dedup-cooldown skip
        {"id": 6, "title": "x", "metadata": {"source": "manual",
                                             "file_path": IN_SCOPE}},  # wrong source
        {"id": 7, "title": "x", "metadata": {"source": "code_health_audit"}},  # no file
    ]
    conn = _Conn(props)
    e = _StubEngine(conn, _Tracker(skip={"proposal:5"}))
    r = await e._pull_proposal_build()
    assert r is None, "every proposal is ineligible -> the lane must no-op"
    assert e.run_build_calls == []
    assert conn.recorded_prs == []


async def test_hub_error_and_empty_list_noop():
    e = _StubEngine(_Conn([], error=True), _Tracker())
    assert await e._pull_proposal_build() is None
    e2 = _StubEngine(_Conn([]), _Tracker())
    assert await e2._pull_proposal_build() is None


async def test_record_failure_is_bookkeeping_not_build_failure():
    """The PR exists once run_build returns it; a hub blip recording it must
    not fail the lane -- the completion sweep still sees the PR via GitHub."""
    conn = _Conn([_prop(12, IN_SCOPE)], record_fails=True)
    e = _StubEngine(conn, _Tracker())
    r = await e._pull_proposal_build()
    assert r is not None and r.get("pr_number") == 99
    assert r["proposal_recorded"] is False


async def test_no_pr_means_no_record_call():
    conn = _Conn([_prop(13, IN_SCOPE)])
    e = _StubEngine(conn, _Tracker(),
                    build_result={"success": False, "stage": "tests_failed"})
    r = await e._pull_proposal_build()
    assert r is not None
    assert conn.recorded_prs == []


def test_both_noop_branches_fall_through_to_the_proposals_lane():
    """A lane wired at one of two no-op exits is a lane with holes (#5862
    family): 'no in-scope issue' AND 'all in-scope issues stale' must both
    try the proposals lane before giving up."""
    src = inspect.getsource(Engine.pull_and_build)
    assert src.count("_pull_proposal_build") >= 2, \
        "one of pull_and_build's no-op branches lost the proposals fall-through"
