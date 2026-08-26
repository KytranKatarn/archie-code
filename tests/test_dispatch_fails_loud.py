"""A failed dispatch must NAME itself, never masquerade as an empty answer (#6037).

`HubConnector.post` never raises — it RETURNS `{"error": ..., "status": N}`.
`dhq_complete` used to end in `resp.get("response", "") or ""`, so every failure
became an EMPTY STRING, indistinguishable from "the model answered nothing".

Twice this attributed infrastructure failures to the model:
  * a stale key file 401'd every call for TEN WEEKS and the build blamed the planner
  * 903s failing over a 404 node, a 600s timeout and a saturated hub, reported as
    "could not parse a JSON op list from the plan"

The sole production caller is wrapped by `_plan`'s `except Exception ->
"dispatch failed: {exc}"` — the handler this signal was written for, which never
once fired.
"""

from __future__ import annotations

import asyncio

import pytest

from archie_engine.build_loop import BuildLoop
from archie_engine.hub.connector import HubConnector


class _Auth:
    def get_headers(self):
        return {}


def _conn(reply):
    hc = HubConnector(hub_url="http://h", auth=_Auth())

    async def fake_post(path, data=None, timeout=None):
        return reply

    hc.post = fake_post
    return hc


class TestFailuresRaise:
    @pytest.mark.parametrize(
        "reply",
        [
            {"error": "Unauthorized", "status": 401},
            {"error": "dispatch produced no response", "status": 502},
            {"error": "timeout after 600s", "status": 0},
            {"error": "HTTP 404", "status": 404},
        ],
    )
    def test_an_error_payload_raises(self, reply):
        with pytest.raises(RuntimeError):
            asyncio.run(_conn(reply).dhq_complete("p"))

    def test_the_message_carries_the_reason_and_status(self):
        with pytest.raises(RuntimeError) as e:
            asyncio.run(_conn({"error": "Unauthorized", "status": 401}).dhq_complete("p"))
        msg = str(e.value)
        assert "Unauthorized" in msg and "401" in msg

    def test_it_no_longer_returns_empty_string_on_failure(self):
        """The exact bug: a failure that reads as a successful empty answer."""
        try:
            out = asyncio.run(_conn({"error": "boom", "status": 500}).dhq_complete("p"))
        except RuntimeError:
            return  # correct
        pytest.fail(f"failure masked as a value: {out!r}")


class TestSuccessPathUnchanged:
    """⚠️ 'The model said nothing' is NOT a failure and must stay a value."""

    def test_normal_reply_returned(self):
        assert asyncio.run(_conn({"response": "hello"}).dhq_complete("p")) == "hello"

    def test_missing_response_key_without_an_error_is_still_empty(self):
        assert asyncio.run(_conn({"success": False}).dhq_complete("p")) == ""

    def test_empty_response_string_is_still_empty(self):
        assert asyncio.run(_conn({"response": ""}).dhq_complete("p")) == ""

    def test_a_non_dict_reply_is_empty_not_a_raise(self):
        assert asyncio.run(_conn("not a dict").dhq_complete("p")) == ""


class TestParseFailureCarriesEvidence:
    """The response is the ONLY thing distinguishing the parse-failure causes."""

    def _plan_err(self, raw):
        loop = BuildLoop.__new__(BuildLoop)
        loop.scope_config = None
        loop.plan_max_retries = 0

        async def fake_dispatch(prompt):
            return raw

        loop.dispatch_fn = fake_dispatch
        ops, err = asyncio.run(loop._plan("do a thing"))
        return err

    def test_python_output_is_quoted_in_the_error(self):
        err = self._plan_err("```python\nasync def dhq_complete(self):\n    pass\n```")
        assert "model returned" in err and "python" in err

    def test_nothing_at_all_says_so_explicitly(self):
        assert "NOTHING" in self._plan_err("")

    def test_the_preview_is_bounded(self):
        err = self._plan_err("x" * 5000)
        assert len(err) < 400, "an unbounded dump would flood the build result"
