"""Provider switching: fleet (sovereign) vs omniroute (benchmark lane) — #6776.

WHY
---
archie-tui runs `archie:7b` on the local fleet; the codex and opencode lanes run
`big-pickle` through omniroute. Different models on different hardware, so their
latency numbers cannot be compared. To benchmark the HARNESS you need all three on
one model — hence a second provider, selectable at runtime via `/model`.

⚠️ WHAT omniroute BYPASSES — the reason it is opt-in and defaults off:
  * the DHQ dispatcher, so no welfare gating, no cold-load queue, no capability
    routing (ADR-013)
  * it proxies to EXTERNAL providers, so egress leaves the infra
  * therefore also `platform_settings.escalation_mode` (measured `ask_first` on
    2026-09-15, i.e. cloud allowed but per-call approval expected) and
    `_cloud_budget_ok`

It exists to MEASURE. Making it the default is an owner/ADR decision, not a config
tweak, and these tests pin the default so that cannot happen by accident.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from archie_engine.inference import InferenceClient


def _resp(status=200, json_data=None):
    r = MagicMock()
    r.status = status
    r.json = AsyncMock(return_value=json_data or {})
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=False)
    return r


_GW_OK = {
    "model": "big-pickle",
    "choices": [{"message": {"role": "assistant", "content": "  gateway says hi  "}}],
    "usage": {"prompt_tokens": 700, "completion_tokens": 42},
}


@pytest.fixture
def both(monkeypatch):
    """A client with BOTH providers configured."""
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://omniroute.invalid:20128/v1")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "gw-key")
    monkeypatch.setenv("OMNIROUTE_MODEL", "auto/coding:free")
    monkeypatch.delenv("ARCHIE_ENGINE_PROVIDER", raising=False)
    return InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="hub-key")


# --------------------------------------------------------------------------- #
# the default is SOVEREIGN — pinned deliberately
# --------------------------------------------------------------------------- #


def test_default_provider_is_fleet(both):
    """THE INVARIANT. If this flips, Lane 3 silently starts egressing externally."""
    assert both.provider == "fleet"


def test_unknown_env_provider_falls_back_to_fleet(monkeypatch):
    """A typo must not silently disable the dispatcher."""
    monkeypatch.setenv("ARCHIE_ENGINE_PROVIDER", "omniroutte")  # typo on purpose
    c = InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="k")
    assert c.provider == "fleet"


def test_env_can_select_omniroute(monkeypatch):
    monkeypatch.setenv("ARCHIE_ENGINE_PROVIDER", "omniroute")
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://omniroute.invalid:20128/v1")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "gw-key")
    c = InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="k")
    assert c.provider == "omniroute"


# --------------------------------------------------------------------------- #
# set_provider refuses what it cannot serve
# --------------------------------------------------------------------------- #


def test_switch_to_omniroute_and_back(both):
    ok, _ = both.set_provider("omniroute")
    assert ok and both.provider == "omniroute"
    ok, _ = both.set_provider("fleet")
    assert ok and both.provider == "fleet"


def test_refuses_unknown_provider(both):
    ok, msg = both.set_provider("gpt5")
    assert not ok and both.provider == "fleet"
    assert "unknown provider" in msg


def test_refuses_omniroute_when_unconfigured(monkeypatch):
    """A switch that would silently fall back is worse than a refusal — it looks
    identical to a working one from the caller's side."""
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    c = InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="k")
    ok, msg = c.set_provider("omniroute")
    assert not ok and c.provider == "fleet"
    assert "not configured" in msg


def test_half_configured_gateway_is_not_enabled(monkeypatch):
    """URL without key — same rule the hub already applies to itself."""
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://omniroute.invalid:20128/v1")
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    c = InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="k")
    assert c.omniroute_enabled is False


# --------------------------------------------------------------------------- #
# routing actually follows the switch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_omniroute_path_returns_usage_in_the_same_shape(both):
    """Both providers must report through ONE shape or they are not comparable."""
    both.set_provider("omniroute")
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, _GW_OK)):
        out = await both.generate("p", model="auto/coding:free")
    assert out["_via"] == "omniroute"
    assert out["response"] == "gateway says hi"
    assert out["prompt_tokens"] == 700
    assert out["completion_tokens"] == 42
    assert out["model"] == "big-pickle"  # what the gateway RESOLVED the alias to


@pytest.mark.asyncio
async def test_chat_also_routes_to_omniroute(both):
    both.set_provider("omniroute")
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, _GW_OK)):
        out = await both.chat([{"role": "user", "content": "hi"}], model="auto/coding:free")
    assert out["_via"] == "omniroute"
    assert out["message"]["content"] == "gateway says hi"
    assert out["completion_tokens"] == 42


@pytest.mark.asyncio
async def test_fleet_provider_does_not_touch_the_gateway(both):
    """NON-VACUITY: prove the switch is what routes, not the mock.

    On fleet, a hub-shaped reply must be consumed — if the gateway branch ran, the
    OpenAI-shaped parser would find no `choices` and fall through to direct.
    """
    hub_ok = {"success": True, "response": "fleet says hi", "model_used": "archie:7b",
              "prompt_tokens": 5, "completion_tokens": 6}
    assert both.provider == "fleet"
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, hub_ok)):
        out = await both.generate("p", model="archie:7b")
    assert out["_via"] == "hub"
    assert out["response"] == "fleet says hi"


@pytest.mark.asyncio
async def test_gateway_outage_falls_back_to_direct(both):
    """Same waiver as the hub path: Lane 3 must never hard-fail on a provider outage."""
    both.set_provider("omniroute")
    calls = {"n": 0}

    def _post(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("gateway refused")
        return _resp(200, {"response": "local", "done": True})

    with patch("aiohttp.ClientSession.post", side_effect=_post):
        out = await both.generate("p", model="x")
    assert out["_via"] == "direct"


@pytest.mark.asyncio
async def test_gateway_non_200_falls_back(both):
    both.set_provider("omniroute")
    calls = {"n": 0}

    def _post(*a, **kw):
        calls["n"] += 1
        return _resp(503, {}) if calls["n"] == 1 else _resp(200, {"response": "local", "done": True})

    with patch("aiohttp.ClientSession.post", side_effect=_post):
        out = await both.generate("p", model="x")
    assert out["_via"] == "direct"


@pytest.mark.asyncio
async def test_constrained_decoding_stays_on_the_direct_path(both):
    """`format=` is the build planner's guarantee of a parseable op-list.

    omniroute advertises response_format, but silently swapping one contract for the
    other is how a planner starts returning prose. Same carve-out the hub has.
    """
    both.set_provider("omniroute")
    with patch("aiohttp.ClientSession.post", return_value=_resp(200, {"message": {"content": "{}"}})):
        out = await both.chat([{"role": "user", "content": "hi"}], model="x", format="json")
    assert out.get("_via") == "direct"
