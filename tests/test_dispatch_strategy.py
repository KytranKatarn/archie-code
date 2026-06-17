"""Tests for DispatchStrategy — build inference routes through DHQ (PLATFORM),
strictly-local by default (ADR-003, #4252)."""

from archie_engine.dispatch_strategy import DispatchStrategy, DispatchTarget
from archie_engine.config import EngineConfig


def _intent(t, conf=0.9, raw=""):
    return {"type": t, "confidence": conf, "raw_input": raw}


# --- build inference routes to PLATFORM (DHQ) when the hub is up ---

def test_code_task_routes_to_platform_when_hub_up():
    d = DispatchStrategy(hub_available=True).decide(_intent("code_task", raw="implement feature X"))
    assert d.target == DispatchTarget.PLATFORM
    assert d.capability == "code_generation"


def test_code_task_capability_resolution():
    s = DispatchStrategy(hub_available=True)
    assert s.decide(_intent("code_task", raw="review this diff")).capability == "code_review"
    assert s.decide(_intent("code_task", raw="refactor the module")).capability == "refactoring"
    assert s.decide(_intent("code_task", raw="write a function")).capability == "code_generation"


def test_knowledge_and_conversation_route_to_platform():
    s = DispatchStrategy(hub_available=True)
    assert s.decide(_intent("knowledge_query")).target == DispatchTarget.PLATFORM
    assert s.decide(_intent("conversation")).target == DispatchTarget.PLATFORM


# --- hub offline → direct-Ollama fallback (the intended ADR-003 fallback) ---

def test_llm_intent_falls_back_to_local_when_hub_down():
    d = DispatchStrategy(hub_available=False).decide(_intent("code_task"))
    assert d.target == DispatchTarget.LOCAL
    assert d.capability == "code_generation"


# --- tool intents are always local (no LLM) ---

def test_tool_intents_always_local():
    s = DispatchStrategy(hub_available=True)
    for t in ("file_operation", "git_operation", "shell_command"):
        assert s.decide(_intent(t)).target == DispatchTarget.LOCAL


# --- strictly-local (default): never escalate to cloud ---

def test_local_only_suppresses_claude_escalation():
    # low confidence + hub up would normally escalate to CLAUDE; strictly-local
    # routes the LLM intent to the PLATFORM (DHQ local cluster) instead.
    d = DispatchStrategy(hub_available=True, local_only=True).decide(_intent("code_task", conf=0.05))
    assert d.target == DispatchTarget.PLATFORM
    assert d.target != DispatchTarget.CLAUDE


def test_local_only_low_conf_tool_intent_stays_local():
    d = DispatchStrategy(hub_available=True, local_only=True).decide(_intent("file_operation", conf=0.05))
    assert d.target == DispatchTarget.LOCAL


# --- legacy: cloud escalation only when explicitly allowed ---

def test_cloud_escalation_when_not_local_only():
    d = DispatchStrategy(hub_available=True, local_only=False).decide(_intent("code_task", conf=0.05))
    assert d.target == DispatchTarget.CLAUDE


# --- config policy: strictly-local by default, env escape hatch ---

def test_config_defaults_to_local_only(monkeypatch):
    monkeypatch.delenv("ARCHIE_ENGINE_ALLOW_CLOUD", raising=False)
    assert EngineConfig().local_only is True


def test_config_allow_cloud_env_opens_escalation(monkeypatch):
    monkeypatch.setenv("ARCHIE_ENGINE_ALLOW_CLOUD", "1")
    assert EngineConfig().local_only is False


def test_config_truthy_allow_cloud_values_open_escalation(monkeypatch):
    # case-insensitive truthy values open cloud escalation
    for val in ("1", "true", "TRUE", "yes", "Yes"):
        monkeypatch.setenv("ARCHIE_ENGINE_ALLOW_CLOUD", val)
        assert EngineConfig().local_only is False, val


def test_config_invalid_allow_cloud_value_fails_safe_to_local(monkeypatch):
    # any falsy / garbage / unset value MUST keep the engine strictly local
    # (fail-safe: never silently open cloud on a typo'd env var)
    for val in ("0", "false", "no", "off", "maybe", "", "  "):
        monkeypatch.setenv("ARCHIE_ENGINE_ALLOW_CLOUD", val)
        assert EngineConfig().local_only is True, val
