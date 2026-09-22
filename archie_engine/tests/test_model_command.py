"""`/model` — the TUI-facing provider toggle (#6776).

Tested against the UNBOUND method with a stub `self`, so these run without standing up
the whole Engine (sessions, skill registry, hub connector, websocket server). The
method is deliberately pure: it reads and writes `self.inference` and returns a string.

WHY IT IS NOT A SKILL
---------------------
Skills are markdown prompt-templates executed BY an LLM (skills/community/*.md).
`/model` changes how the engine ROUTES, so routing it through the model it
reconfigures would be circular — and an ingested community skill named "model" could
shadow it. It is handled before the registry, and `test_unknown_slash_is_not_swallowed`
pins that everything else still falls through.
"""

import pytest

from archie_engine.engine import Engine
from archie_engine.inference import InferenceClient


class _Stub:
    """Minimal stand-in for the engine — only `.inference` is touched."""

    def __init__(self, inference):
        self.inference = inference


def _call(stub, text):
    return Engine._handle_control_command(stub, text)


@pytest.fixture
def stub(monkeypatch):
    monkeypatch.setenv("OMNIROUTE_BASE_URL", "http://omniroute.invalid:20128/v1")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "gw-key")
    monkeypatch.setenv("OMNIROUTE_MODEL", "auto/coding:free")
    monkeypatch.delenv("ARCHIE_ENGINE_PROVIDER", raising=False)
    return _Stub(InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="hub-key"))


def test_unknown_slash_is_not_swallowed(stub):
    """THE REGRESSION RISK. Returning anything but None here would break every skill."""
    assert _call(stub, "/commit fix the thing") is None
    assert _call(stub, "/review") is None
    assert _call(stub, "not a command at all") is None


def test_bare_model_reports_state_without_changing_it(stub):
    out = _call(stub, "/model")
    assert "fleet" in out and "omniroute" in out
    assert stub.inference.provider == "fleet", "a status query must not switch anything"


def test_status_names_the_gateway_model(stub):
    """Showing which model omniroute would use is the point — it is what makes the
    lane comparable to codex/opencode."""
    assert "auto/coding:free" in _call(stub, "/model")


def test_switch_to_omniroute_warns_it_leaves_the_fleet(stub):
    out = _call(stub, "/model omniroute")
    assert stub.inference.provider == "omniroute"
    low = out.lower()
    assert "outside the fleet" in low or "gateway" in low, (
        "switching off the sovereign path must SAY so — a silent switch is how an "
        "external egress becomes the normal path unnoticed"
    )


def test_switch_back_to_fleet(stub):
    _call(stub, "/model omniroute")
    out = _call(stub, "/model fleet")
    assert stub.inference.provider == "fleet"
    assert "fleet" in out


def test_bad_provider_reports_unchanged(stub):
    out = _call(stub, "/model gpt5")
    assert stub.inference.provider == "fleet"
    assert "unchanged" in out.lower()


def test_unconfigured_gateway_is_refused_not_silently_accepted(monkeypatch):
    """A switch that would just fall back is indistinguishable from a working one."""
    monkeypatch.delenv("OMNIROUTE_BASE_URL", raising=False)
    monkeypatch.delenv("OMNIROUTE_API_KEY", raising=False)
    s = _Stub(InferenceClient(hub_url="http://hub.invalid:3000", hub_api_key="k"))
    out = _call(s, "/model omniroute")
    assert s.inference.provider == "fleet"
    assert "unchanged" in out.lower() and "not configured" in out.lower()


def test_missing_inference_client_does_not_crash():
    """The TUI must get a message, never a traceback."""
    out = _call(_Stub(None), "/model")
    assert "not attached" in out.lower()
