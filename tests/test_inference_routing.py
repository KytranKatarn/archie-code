"""Lane 3 inference routing — dispatcher first, direct fallback (ADR-013).

These pin the DECISIONS, not the network. Every case here is pure: which path a call
takes, and whether the transcript survives the trip. The live end-to-end proof
(`_via: hub`, executed on USS-246, logged to task_execution_log) was taken by hand on
2026-08-25 and cannot be asserted here without a hub.
"""

from __future__ import annotations

import pytest

from archie_engine.inference import InferenceClient

HUB = "http://100.64.0.4:3000"


@pytest.fixture(autouse=True)
def _no_ambient_hub_env(monkeypatch):
    """Assert on EXPLICIT constructor args, never on the ambient environment.

    ⚠️ `InferenceClient.__init__` falls back to ARCHIE_HUB_URL / ARCHIE_HUB_API_KEY /
    INTERNAL_API_KEY when an arg is falsy. Those vars are SET wherever the engine
    actually runs, so without this fixture `hub_url=""` silently resolved to the real
    hub and `test_key_without_url_is_not_enabled` asserted False against True.

    It passed in CI (clean env) and failed in the engine container — i.e. it was green
    exactly where nothing runs and red exactly where everything does. Measured
    2026-08-26: 2 of the 12 red tests on main were this.
    """
    for var in ("ARCHIE_HUB_URL", "ARCHIE_HUB_API_KEY", "INTERNAL_API_KEY",
                "ARCHIE_ENGINE_PIN_MODEL"):
        monkeypatch.delenv(var, raising=False)


def _client(**kw) -> InferenceClient:
    return InferenceClient("http://127.0.0.1:11434", **kw)


class TestHubEnablement:
    def test_no_hub_configured_means_direct(self, monkeypatch):
        monkeypatch.delenv("ARCHIE_HUB_URL", raising=False)
        monkeypatch.delenv("ARCHIE_HUB_API_KEY", raising=False)
        monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
        assert _client().hub_enabled is False

    def test_url_without_key_is_not_enabled(self):
        """A half-configured hub is not a hub — it would 401 every call."""
        assert _client(hub_url=HUB, hub_api_key="").hub_enabled is False

    def test_key_without_url_is_not_enabled(self):
        assert _client(hub_url="", hub_api_key="k").hub_enabled is False

    def test_both_present_enables_the_dispatcher_path(self):
        assert _client(hub_url=HUB, hub_api_key="k").hub_enabled is True


class TestFormatStaysDirect:
    """⚠️ The build planner's op-list depends on constrained decoding (#380).

    /api/internal/dhq/chat has NO `format` passthrough, so routing those calls through
    it would silently drop the constraint and return prose where JSON is expected — a
    parse failure that reads like a model-quality problem and is not.
    """

    def test_format_forces_direct_even_with_hub_available(self):
        c = _client(hub_url=HUB, hub_api_key="k")
        assert c._should_use_hub() is True
        assert c._should_use_hub("json") is False

    def test_schema_dict_also_forces_direct(self):
        c = _client(hub_url=HUB, hub_api_key="k")
        assert c._should_use_hub({"type": "object"}) is False

    def test_falsy_format_still_uses_the_hub(self):
        """`format=None`/`""` is "no constraint", not "constrained to nothing"."""
        c = _client(hub_url=HUB, hub_api_key="k")
        assert c._should_use_hub(None) is True
        assert c._should_use_hub("") is True


class TestModelPinning:
    """Pinning a model forces hub routing and defeats fleet placement."""

    def test_pinning_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv("ARCHIE_ENGINE_PIN_MODEL", raising=False)
        assert _client(hub_url=HUB, hub_api_key="k").pin_model is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
    def test_pinning_can_be_opted_into(self, monkeypatch, raw):
        monkeypatch.setenv("ARCHIE_ENGINE_PIN_MODEL", raw)
        assert _client(hub_url=HUB, hub_api_key="k").pin_model is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", ""])
    def test_other_values_do_not_pin(self, monkeypatch, raw):
        monkeypatch.setenv("ARCHIE_ENGINE_PIN_MODEL", raw)
        assert _client(hub_url=HUB, hub_api_key="k").pin_model is False


class TestFlatten:
    """The endpoint takes one prompt; chat() takes a transcript. Nothing may be lost."""

    def test_system_turns_are_lifted_out(self):
        body, system = InferenceClient._flatten(
            [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
        )
        assert system == "S"
        assert "S" not in body

    def test_single_turn_is_not_role_prefixed(self):
        body, system = InferenceClient._flatten([{"role": "user", "content": "only"}])
        assert body == "only"
        assert system is None

    def test_multi_turn_keeps_every_turn(self):
        """Truncating to the last turn would silently discard context."""
        body, _ = InferenceClient._flatten(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ]
        )
        assert "first" in body and "second" in body and "third" in body

    def test_multiple_system_turns_are_joined(self):
        _, system = InferenceClient._flatten(
            [
                {"role": "system", "content": "A"},
                {"role": "system", "content": "B"},
                {"role": "user", "content": "U"},
            ]
        )
        assert system is not None and "A" in system and "B" in system

    def test_missing_content_does_not_raise(self):
        """Malformed turns must degrade, not crash the builder."""
        body, system = InferenceClient._flatten(
            [{"role": "user"}, {"role": "assistant", "content": None}]
        )
        assert isinstance(body, str)
        assert system is None
