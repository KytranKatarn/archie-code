"""Tests for the autonomous build loop (#4256) — orchestration + ADR-003 safety
invariants: scope-guarded apply, file cap, deploy-only-on-green, NEVER merges."""

from archie_engine.build_loop import (
    BuildLoop, _parse_ops, _branch_name, DEFAULT_MAX_FILES,
)
from archie_engine.tools.base import ToolResult


class FakeTools:
    """Records every tool call; returns configured ToolResults per (name, operation)."""

    def __init__(self):
        self.calls = []
        self.responses = {}
        self.default_ok = ToolResult(success=True, output="ok")
        self.pr_result = ToolResult(success=True, output="PR",
                                    metadata={"number": 7, "url": "https://gh/pr/7"})

    def set(self, name, operation, result):
        self.responses[(name, operation)] = result

    async def execute(self, tool_name, **kwargs):
        op = kwargs.get("operation")
        self.calls.append((tool_name, op, kwargs))
        if (tool_name, op) in self.responses:
            return self.responses[(tool_name, op)]
        if tool_name == "github_ops" and op == "pr_create":
            return self.pr_result
        return self.default_ok

    def seq(self):
        return [(n, o) for (n, o, _k) in self.calls]


def _dispatch(ops_json):
    async def _d(prompt):
        return ops_json
    return _d


OPS = '[{"path": "archie_engine/x.py", "action": "write", "content": "x = 1\\n"}]'


# --- happy path ---------------------------------------------------------

async def test_happy_path_opens_pr_in_order():
    tools = FakeTools()
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(OPS)).run("add feature X")
    assert r.success, (r.stage, r.error)
    assert r.pr_url == "https://gh/pr/7" and r.pr_number == 7
    assert r.files == ["archie_engine/x.py"]
    assert r.tests_passed
    seq = tools.seq()
    for step in [("git_ops", "branch"), ("file_ops", "write"), ("shell_ops", None),
                 ("git_ops", "add"), ("git_ops", "commit"), ("git_ops", "push"),
                 ("github_ops", "pr_create")]:
        assert step in seq, step
    # branch happens before apply; test happens before push
    assert seq.index(("shell_ops", None)) < seq.index(("git_ops", "push"))


async def test_never_merges():
    tools = FakeTools()
    await BuildLoop(tools=tools, dispatch_fn=_dispatch(OPS)).run("x")
    assert not any("merge" in str(op).lower() for (_n, op, _k) in tools.calls)


# --- scope guard --------------------------------------------------------

async def test_out_of_scope_path_rejected_before_any_write():
    tools = FakeTools()
    bad = '[{"path": ".env", "action": "write", "content": "SECRET=1"}]'
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(bad)).run("write env")
    assert not r.success and r.stage == "apply"
    s = tools.seq()
    assert ("file_ops", "write") not in s
    assert ("git_ops", "push") not in s and ("github_ops", "pr_create") not in s


async def test_unknown_action_rejected():
    tools = FakeTools()
    bad = '[{"path": "archie_engine/x.py", "action": "delete"}]'
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(bad)).run("del")
    assert not r.success and r.stage == "apply"


# --- file cap -----------------------------------------------------------

async def test_file_cap_enforced():
    tools = FakeTools()
    many = "[" + ",".join(
        '{"path":"archie_engine/f%d.py","action":"write","content":"x"}' % i
        for i in range(DEFAULT_MAX_FILES + 1)
    ) + "]"
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(many)).run("big")
    assert not r.success and r.stage == "plan"
    assert "too large" in r.error.lower()
    assert ("file_ops", "write") not in tools.seq()


# --- deploy only on green ----------------------------------------------

async def test_red_build_does_not_deploy():
    tools = FakeTools()
    tools.set("shell_ops", None, ToolResult(success=False, error="2 failed"))
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(OPS)).run("add feature")
    assert not r.success and r.stage == "test"
    s = tools.seq()
    assert ("git_ops", "push") not in s and ("github_ops", "pr_create") not in s


# --- failure propagation ------------------------------------------------

async def test_branch_failure_stops_immediately():
    tools = FakeTools()
    tools.set("git_ops", "branch", ToolResult(success=False, error="exists"))
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(OPS)).run("x")
    assert not r.success and r.stage == "branch"
    assert ("file_ops", "write") not in tools.seq()


async def test_push_failure_stops_before_pr():
    tools = FakeTools()
    tools.set("git_ops", "push", ToolResult(success=False, error="refusing protected branch"))
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch(OPS)).run("x")
    assert not r.success and r.stage == "push"
    assert ("github_ops", "pr_create") not in tools.seq()


async def test_malformed_plan_fails_gracefully():
    tools = FakeTools()
    r = await BuildLoop(tools=tools, dispatch_fn=_dispatch("sorry, cannot do that")).run("x")
    assert not r.success and r.stage == "plan"


async def test_dispatch_exception_is_graceful():
    async def boom(prompt):
        raise RuntimeError("hub down")
    r = await BuildLoop(tools=FakeTools(), dispatch_fn=boom).run("x")
    assert not r.success and r.stage == "plan" and "hub down" in r.error


# --- telemetry ----------------------------------------------------------

async def test_telemetry_best_effort():
    class FakeConn:
        def __init__(self):
            self.logged = []
        async def log_job(self, **kw):
            self.logged.append(kw)

    conn = FakeConn()
    loop = BuildLoop(tools=FakeTools(), dispatch_fn=_dispatch(OPS), connector=conn)
    r = await loop.run("feat")
    await loop.emit_telemetry(r)
    assert conn.logged and conn.logged[0]["success"] is True
    assert conn.logged[0]["agent_name"] == "A.R.C.H.I.E. Engine"
    assert conn.logged[0]["files_changed"] == ["archie_engine/x.py"]


async def test_telemetry_failure_never_raises():
    class BoomConn:
        async def log_job(self, **kw):
            raise RuntimeError("nope")
    loop = BuildLoop(tools=FakeTools(), dispatch_fn=_dispatch(OPS), connector=BoomConn())
    r = await loop.run("feat")
    await loop.emit_telemetry(r)  # must not raise
    assert r.success


# --- pure helpers -------------------------------------------------------

def test_parse_ops_tolerant():
    assert _parse_ops('```json\n[{"path":"a"}]\n```') == [{"path": "a"}]
    assert _parse_ops('Here: [{"path":"a"}] done') == [{"path": "a"}]
    assert _parse_ops("no json") is None
    assert _parse_ops('{"not":"a list"}') is None
    assert _parse_ops("") is None
    # non-dict items dropped
    assert _parse_ops('[{"path":"a"}, 5, "x"]') == [{"path": "a"}]


def test_branch_name_slugifies():
    # #4322: a short unique suffix is appended so retries never collide — assert the
    # slugified prefix, not an exact match.
    assert _branch_name("Add Feature X!").startswith("engine/add-feature-x-")
    assert _branch_name("").startswith("engine/task-")
