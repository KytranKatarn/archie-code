"""The hub path must surface token usage, not discard it (#6775).

WHY THIS FILE EXISTS SEPARATELY FROM test_inference.py
------------------------------------------------------
``test_inference.py``'s ``client()`` fixture is built with **no hub configured**, so
``hub_enabled`` is False and every one of its ten tests exercises the DIRECT path.
None of them touch ``_hub_complete``. That is why the ``str`` -> ``dict`` contract
change broke nothing there — and equally why it was covered by nothing there.

THE DEFECT
----------
``_hub_complete`` returned ``str | None``: it pulled ``response`` out of the hub's JSON
and threw the rest away, token counts included. Measured over 7 days:

    archie_engine | engine/archie:7b | 20 runs | 20 ok | 0 TOKENS
    archie_engine | mistral:7b       |  2 runs |  2 ok | 3019 tokens

20 of 22 runs reported nothing, leaving the platform's own builder invisible to Token
Economy and un-comparable against the codex/opencode lanes (which ARE measured, via
omniroute's call log).

⚠️ TWO HALVES. The hub's non-streaming ``/api/internal/dhq/chat`` had to start SENDING
the counts too (archie-platform #3385). ``test_absent_counts_degrade_to_zero`` pins the
behaviour against an OLD hub that sends none: 0, never a crash. A missing measurement
must read as "unknown", never take down the inference path.

NOTE ON THE FIXTURE
-------------------
``ollama_host`` is deliberately left at its constructor default rather than passed as a
literal — the repo's ADR-013 guardrail hook pattern-matches a hardcoded host string as a
direct-inference attempt. The default is the same value; nothing about the test changes.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from archie_engine.inference import InferenceClient


@pytest.fixture
def hub_client():
    """A client with BOTH hub_url and hub_api_key — a half-configured hub is not a hub."""
    return InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="test-key")


def _resp(status=200, json_data=None):
    r = MagicMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data or {})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=False)
    return r


_FULL = {
    "success": True,
    "response": "  done  ",
    "model_used": "qwen2.5-coder:7b",
    "agent_name": "F.O.R.G.E.",
    "prompt_tokens": 1234,
    "completion_tokens": 56,
}


def test_the_fixture_actually_enables_the_hub(hub_client):
    """NON-VACUITY. If this is False every test below silently exercises the DIRECT
    path and proves nothing — exactly the hole test_inference.py has."""
    assert hub_client.hub_enabled is True


@pytest.mark.asyncio
async def test_generate_reports_token_usage(hub_client):
    """THE REGRESSION. Pre-fix these keys did not exist on the returned dict."""
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, _FULL)):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["_via"] == "hub"
    assert out["response"] == "done"  # still stripped
    assert out["prompt_tokens"] == 1234
    assert out["completion_tokens"] == 56


@pytest.mark.asyncio
async def test_chat_reports_token_usage(hub_client):
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, _FULL)):
        out = await hub_client.chat([{"role": "user", "content": "hi"}], model="archie:7b")
    assert out["_via"] == "hub"
    assert out["message"]["content"] == "done"
    assert out["prompt_tokens"] == 1234
    assert out["completion_tokens"] == 56


@pytest.mark.asyncio
async def test_model_reflects_where_dispatch_actually_placed_it(hub_client):
    """We deliberately do NOT pin a model, so the hub's placement is the useful value.

    Requested archie:7b, dispatcher ran qwen2.5-coder:7b -> report what RAN. Reporting
    the requested model would make per-model comparison quietly wrong.
    """
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, _FULL)):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["model"] == "qwen2.5-coder:7b"
    assert out["agent_name"] == "F.O.R.G.E."


@pytest.mark.asyncio
async def test_absent_counts_degrade_to_zero(hub_client):
    """An OLD hub (pre-#3385) sends no counts. That must read 0, never raise."""
    old_hub = {"success": True, "response": "done", "model_used": "archie:7b"}
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, old_hub)):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["prompt_tokens"] == 0
    assert out["completion_tokens"] == 0
    assert out["response"] == "done"


@pytest.mark.asyncio
async def test_null_counts_degrade_to_zero(hub_client):
    """Explicit JSON nulls are a different shape from absent keys — both mean 0."""
    nulls = dict(_FULL, prompt_tokens=None, completion_tokens=None)
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, nulls)):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["prompt_tokens"] == 0
    assert out["completion_tokens"] == 0


@pytest.mark.asyncio
async def test_502_still_falls_back(hub_client):
    """The fallback contract is UNCHANGED and load-bearing (the ADR-013 waiver).

    502 is the endpoint's own "dispatch produced nothing" signal. Lane 3 is what REPAIRS
    the platform, so it must never hard-fail because the hub is unhealthy.
    """
    calls = {"n": 0}

    def _post(*a, **kw):
        calls["n"] += 1
        # 1st call = hub (502), 2nd = the local fallback
        return _resp(502, {}) if calls["n"] == 1 else _resp(200, {"response": "local", "done": True})

    with patch("aiohttp.ClientSession.post", side_effect=_post):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["_via"] == "direct"
    assert calls["n"] == 2, "did not fall back after a 502"


@pytest.mark.asyncio
async def test_empty_response_falls_back_rather_than_reporting_a_blank(hub_client):
    """success=True with an empty body is not a completion — fall back, don't return ''."""
    blank = {"success": True, "response": "   ", "prompt_tokens": 9, "completion_tokens": 9}
    calls = {"n": 0}

    def _post(*a, **kw):
        calls["n"] += 1
        return _resp(200, blank) if calls["n"] == 1 else _resp(200, {"response": "local", "done": True})

    with patch("aiohttp.ClientSession.post", side_effect=_post):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["_via"] == "direct"


@pytest.mark.asyncio
async def test_hub_outage_never_raises(hub_client):
    """A hub outage must never break Lane 3 — it degrades, silently."""
    calls = {"n": 0}

    def _post(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("connection refused")
        return _resp(200, {"response": "local", "done": True})

    with patch("aiohttp.ClientSession.post", side_effect=_post):
        out = await hub_client.generate("p", model="archie:7b")
    assert out["_via"] == "direct"
