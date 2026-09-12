"""A delegated turn returns the team's ANSWER, not the submit receipt (#6733).

Before this, `dispatch()` submitted and returned immediately, so the assistant
turn recorded in session history was
"Delegated to the A.R.C.H.I.E. team as task #N". The real answer landed in the
hub's work_notes, where the conversation could never see it -- which is why a
TUI follow-up ("expand on that") had nothing to expand, even after #6729 made
the engine send conversation context in the first place.

Every test here drives the real `dispatch`/`await_delegation` against a fake
transport. The poll's timing is collapsed by stubbing `asyncio.sleep`, so the
tests exercise the loop's actual control flow rather than a reimplementation of
it, and still run in milliseconds.
"""

# Every test is an async pytest-asyncio test rather than a sync one calling
# `asyncio.run(...)`. That is not style: `asyncio.run` CLEARS the thread's
# current event loop when it returns, and archie_engine.engine._mcp_tool_handler
# still reaches for the deprecated `asyncio.get_event_loop()`. Sync tests here
# turned test_engine.py::test_mcp_file_read_and_shell_exec_are_confined red with
# "There is no current event loop in thread 'MainThread'" purely by running
# before it -- a test file that breaks its neighbours is a defect of its own.
import pytest

from archie_engine.hub import connector as conn_mod
from archie_engine.hub.connector import HubConnector


class _FakeAuth:
    def get_headers(self):
        return {}

    def get_node_headers(self):
        return {}


def _connector():
    return HubConnector("http://hub.invalid", _FakeAuth())


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Collapse the poll interval to zero.

    The loop still runs every iteration -- only the waiting goes -- so a bug in
    the control flow still shows up. Deliberately done by moving the module
    CONSTANT, never by patching `asyncio.sleep` itself: patching a stdlib module
    is global for the duration of the test, and the first cut of this file did
    exactly that and turned three unrelated tests red the moment it joined the
    suite (they passed in isolation, which is what gave it away).
    """
    monkeypatch.setattr(conn_mod, "_DELEGATION_POLL_INTERVAL_SEC", 0)


def _install(c, *, submit, statuses):
    """Stub the two HTTP verbs. `statuses` is consumed one per poll; the last
    entry repeats, so a test can express "pending forever"."""
    seq = list(statuses)
    calls = {"status": 0}

    async def fake_post(path, data=None, timeout=None):
        assert path == "/api/internal/delegation/submit"
        return submit

    async def fake_get(path, params=None, timeout=None):
        assert path.startswith("/api/internal/delegation/")
        assert path.endswith("/status")
        i = min(calls["status"], len(seq) - 1)
        calls["status"] += 1
        return seq[i]

    c.post = fake_post
    c.get = fake_get
    return calls


_PENDING = {"status": "pending", "terminal": False, "result": None}


def _done(result, source="delegation_output", status="completed"):
    return {
        "status": status,
        "terminal": True,
        "result": result,
        "result_source": source,
        "failure": None,
        "capability": "code",
    }


# ---------------------------------------------------------------------------
# the answer replaces the receipt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_settled_task_returns_the_answer_not_the_receipt():
    c = _connector()
    _install(c, submit={"task_id": 42}, statuses=[_done("42 is the answer.")])
    out = await c.dispatch("what is 6*7?")
    assert out["response"] == "42 is the answer."
    assert out["settled"] is True
    assert out["task_id"] == 42
    assert "Delegated to the A.R.C.H.I.E. team" not in out["response"]


@pytest.mark.asyncio
async def test_it_keeps_polling_while_the_task_is_still_running():
    """The measured median is ~27s from submit to first note, so the first read
    is almost always 'pending'. Giving up on it would fix nothing."""
    c = _connector()
    calls = _install(
        c,
        submit={"task_id": 7},
        statuses=[_PENDING, _PENDING, _PENDING, _done("done at last")],
    )
    out = await c.dispatch("something slow")
    assert out["response"] == "done at last"
    assert calls["status"] == 4


@pytest.mark.asyncio
async def test_the_known_tool_path_answer_survives_too():
    """379 of 451 completed delegations have no delegation_output at all; the
    hub resolves that and hands back `result` either way."""
    c = _connector()
    _install(
        c,
        submit={"task_id": 9},
        statuses=[_done("Documented PR #3309 -> KB vault_note #315657",
                        source="delegation_result")],
    )
    out = await c.dispatch("document that PR")
    assert out["response"].startswith("Documented PR #3309")
    assert out["result_source"] == "delegation_result"


# ---------------------------------------------------------------------------
# every way it can NOT settle -- and none of them may lie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_task_that_never_settles_falls_back_to_the_receipt():
    """The wall is not an error. Exceeding it returns exactly what the engine
    has always returned, so a slow answer degrades to the old behaviour rather
    than to a hang or a fabricated reply."""
    c = _connector()
    _install(c, submit={"task_id": 5}, statuses=[_PENDING])
    out = await c.dispatch("very slow thing")
    assert "Delegated to the A.R.C.H.I.E. team as task #5" in out["response"]
    assert out["settled"] is False


@pytest.mark.asyncio
async def test_the_wall_actually_bounds_the_poll():
    """Without a bound, a stuck task holds the websocket open forever -- the
    engine handles one message per connection at a time.

    `interval_sec=0` keeps the arithmetic honest (30 reads for a 30s wall at a
    1s divisor) while doing no real waiting -- the poll COUNT is what bounds the
    loop, so this exercises the actual bound rather than a shortened copy of it.
    """
    c = _connector()
    calls = _install(c, submit={"task_id": 5}, statuses=[_PENDING])
    out = await c.await_delegation(5, wall_sec=30, interval_sec=0)
    assert out["settled"] is False
    assert out["reason"] == "timeout"
    assert calls["status"] == 30


@pytest.mark.asyncio
async def test_a_zero_wall_still_probes_once():
    """A wall of 0 means "don't wait", not "don't look" -- the answer may
    already be there for a known-tool shortcut that finished in ~1s."""
    c = _connector()
    calls = _install(c, submit={"task_id": 5}, statuses=[_done("instant")])
    out = await c.await_delegation(5, wall_sec=0)
    assert calls["status"] == 1
    assert out["settled"] is True
    assert out["result"] == "instant"


@pytest.mark.asyncio
async def test_an_old_hub_is_not_polled_at_all():
    """The engine image and the platform deploy independently. A hub without
    #6733's `terminal` field answers this route happily and will NEVER report
    terminal -- polling it burns the whole wall on every delegated turn. One
    probe, then fall back."""
    c = _connector()
    calls = _install(
        c,
        submit={"task_id": 11},
        statuses=[{"status": "completed", "work_notes": "...", "title": "t"}],
    )
    out = await c.dispatch("anything")
    assert calls["status"] == 1, "an unsupported hub must be probed exactly once"
    assert out["settled"] is False
    assert "Delegated to the A.R.C.H.I.E. team" in out["response"]


@pytest.mark.asyncio
async def test_a_transient_read_error_does_not_abort_the_poll():
    """`get()` RETURNS an error dict rather than raising, and the hub restarting
    mid-poll is a real event (~25s). Treating one bad read as final would drop
    an answer that is seconds away."""
    c = _connector()
    _install(
        c,
        submit={"task_id": 3},
        statuses=[
            {"error": "Cannot connect to host", "status": 0},
            {"error": "HTTP 502", "status": 502},
            _done("recovered"),
        ],
    )
    out = await c.dispatch("resilient")
    assert out["response"] == "recovered"
    assert out["settled"] is True


@pytest.mark.asyncio
async def test_a_failed_task_says_so_instead_of_returning_a_receipt():
    """A receipt tells the user to watch a feed for an answer that is never
    coming. Report the failure."""
    c = _connector()
    _install(
        c,
        submit={"task_id": 88},
        statuses=[{
            "status": "blocked",
            "terminal": True,
            "result": None,
            "result_source": None,
            "failure": "no agent has capability 'astrology'",
        }],
    )
    out = await c.dispatch("cast a horoscope")
    assert "could not complete task #88" in out["response"]
    assert "astrology" in out["response"]
    assert out["settled"] is True


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
@pytest.mark.asyncio
async def test_a_terminal_task_with_an_empty_result_never_presents_it_as_the_answer(blank):
    """An empty string handed over as the reply is indistinguishable from "the
    agent answered nothing" -- exactly the masking this change removes. Fall
    back to the receipt, which at least points at the task."""
    c = _connector()
    _install(c, submit={"task_id": 4}, statuses=[_done(blank)])
    out = await c.dispatch("x")
    assert "Delegated to the A.R.C.H.I.E. team as task #4" in out["response"]
    assert out["settled"] is False


@pytest.mark.asyncio
async def test_a_submit_error_is_returned_untouched_and_never_polled():
    c = _connector()
    calls = _install(c, submit={"error": "HTTP 401", "status": 401}, statuses=[_PENDING])
    out = await c.dispatch("x")
    assert out == {"error": "HTTP 401", "status": 401}
    assert calls["status"] == 0


@pytest.mark.asyncio
async def test_a_submit_with_no_task_id_is_not_polled():
    """Nothing to poll. Polling `/delegation/None/status` would 404 for the
    whole wall and look like a slow task."""
    c = _connector()
    calls = _install(c, submit={"ok": True}, statuses=[_PENDING])
    out = await c.dispatch("x")
    assert calls["status"] == 0
    assert out["settled"] is False


@pytest.mark.asyncio
async def test_await_result_false_restores_fire_and_forget():
    c = _connector()
    calls = _install(c, submit={"task_id": 1}, statuses=[_done("would have been the answer")])
    out = await c.dispatch("x", await_result=False)
    assert calls["status"] == 0
    assert "Delegated to the A.R.C.H.I.E. team as task #1" in out["response"]


# ---------------------------------------------------------------------------
# the submit payload must not regress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_polling_did_not_disturb_the_submit_contract():
    """#6729's conversation transport and #3310's `reason` both ride this POST.
    Adding the poll must not move or drop either."""
    seen = {}

    c = _connector()

    async def fake_post(path, data=None, timeout=None):
        seen.update({"path": path, "data": data})
        return {"task_id": 1}

    async def fake_get(path, params=None, timeout=None):
        return _done("ok")

    c.post = fake_post
    c.get = fake_get
    await c.dispatch(
        "the prompt",
        agent_target="capability:research",
        user_context={"working_dir": "/w"},
        conversation=[{"role": "user", "content": "earlier"}],
    )
    assert seen["path"] == "/api/internal/delegation/submit"
    assert seen["data"]["reason"] == "the prompt"
    assert seen["data"]["capability"] == "research"
    # top-level, never inside args -- args is rendered as truncated raw JSON
    assert seen["data"]["conversation"] == [{"role": "user", "content": "earlier"}]
    assert "conversation" not in seen["data"]["args"]


@pytest.mark.asyncio
async def test_the_default_wall_covers_the_measured_tail():
    """Measured 2026-09-12 over the 20 most recent delegations: median 27s to
    the first work note, max 160s. A default under that throws away answers
    that were about to arrive."""
    assert conn_mod._DELEGATION_POLL_SEC >= 160


@pytest.mark.parametrize("interval,expected_polls", [(0.5, 2), (0.25, 4), (2.0, 1)])
@pytest.mark.asyncio
async def test_a_sub_second_interval_does_not_divide_by_zero(interval, expected_polls):
    """The poll count is a CEIL of wall/interval. Computed in ints it divides by
    zero for any interval under 1s, because int(0.5) == 0 -- a latent crash in
    anything that tightens the pacing. The expected counts also pin the ceil:
    a 1s wall at 0.25s is 4 reads, not 1 and not 5."""
    c = _connector()
    calls = _install(c, submit={"task_id": 1}, statuses=[_PENDING])
    out = await c.await_delegation(1, wall_sec=1, interval_sec=interval)
    assert out["settled"] is False
    assert out["reason"] == "timeout"
    assert calls["status"] == expected_polls


@pytest.mark.parametrize("interval", [0, None])
@pytest.mark.asyncio
async def test_a_zero_or_missing_interval_is_sanitised_not_crashed(interval):
    """Belt and braces on the same division."""
    c = _connector()
    _install(c, submit={"task_id": 1}, statuses=[_done("ok")])
    out = await c.await_delegation(1, wall_sec=5, interval_sec=interval)
    assert out["settled"] is True
