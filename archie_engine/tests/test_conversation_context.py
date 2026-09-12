"""The platform dispatch carries recent turns, not just a count (#6729).

`user_context` sent `history_length` — a COUNT — and the turns themselves never
crossed. Measured on platform task #6727: one turn after answering "Titan", the
agent was asked *"Is it bigger than the planet Mercury? Answer in one sentence
and name it explicitly"*, could not name it, and answered "No" — the opposite of
the truth. It never asked what "it" meant; nothing told it a referent existed.
"""

import pytest

from archie_engine.router import (
    _CONV_MAX_CHARS_PER_TURN,
    _CONV_MAX_TURNS,
    recent_conversation,
)


def test_keeps_the_newest_turns():
    """A follow-up refers to the LAST exchange, so the tail must survive."""
    hist = [{"role": "user", "content": f"m{i}"} for i in range(_CONV_MAX_TURNS + 3)]
    out = recent_conversation(hist)
    assert len(out) == _CONV_MAX_TURNS
    assert out[-1]["content"] == f"m{_CONV_MAX_TURNS + 2}"
    assert out[0]["content"] != "m0"


def test_output_is_oldest_first():
    out = recent_conversation([{"role": "user", "content": f"m{i}"} for i in range(3)])
    assert [t["content"] for t in out] == ["m0", "m1", "m2"]


def test_only_dialogue_roles_survive():
    out = recent_conversation(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": "{}"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    assert [t["role"] for t in out] == ["user", "assistant"]


def test_long_turn_is_truncated_not_dropped():
    out = recent_conversation([{"role": "user", "content": "x" * 4000}])
    assert len(out) == 1
    assert out[0]["content"].endswith("[…truncated]")
    assert len(out[0]["content"]) <= _CONV_MAX_CHARS_PER_TURN + len(" […truncated]")


def test_carries_the_referent_a_followup_needs():
    """The #6727 regression, as an assertion."""
    out = recent_conversation(
        [
            {"role": "user", "content": "Name the largest moon of Saturn."},
            {"role": "assistant", "content": "Titan"},
        ]
    )
    assert any(t["content"] == "Titan" for t in out)


@pytest.mark.parametrize(
    "junk",
    [None, "str", 7, {"role": "user", "content": "bare dict"}, [None], [{"role": "user"}],
     [{"content": "no role"}], [{"role": "user", "content": "  "}], [{"role": "x", "content": "y"}]],
)
def test_malformed_history_yields_nothing_and_never_raises(junk):
    """History is best-effort context; a bad row must not cost the dispatch."""
    assert recent_conversation(junk) == []
