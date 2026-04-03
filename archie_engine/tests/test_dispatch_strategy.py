"""Tests for DispatchStrategy — local vs platform vs escalation routing."""

import pytest
from archie_engine.dispatch_strategy import DispatchStrategy, DispatchTarget


@pytest.fixture
def strategy_connected():
    """Strategy with hub connected."""
    return DispatchStrategy(hub_available=True)


@pytest.fixture
def strategy_offline():
    """Strategy with no hub."""
    return DispatchStrategy(hub_available=False)


def test_conversation_routes_to_platform_when_connected(strategy_connected):
    """Conversation needs LLM — routes through Bridge for agent-safe dispatch."""
    intent = {"type": "conversation", "confidence": 0.3, "raw_input": "hello"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.PLATFORM


def test_conversation_falls_back_local_when_offline(strategy_offline):
    """Conversation uses direct Ollama only when hub is offline."""
    intent = {"type": "conversation", "confidence": 0.3, "raw_input": "hello"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_file_operation_stays_local(strategy_connected):
    intent = {"type": "file_operation", "confidence": 0.6, "raw_input": "read config.py"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_git_operation_stays_local(strategy_connected):
    intent = {"type": "git_operation", "confidence": 0.5, "raw_input": "git status"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_shell_command_stays_local(strategy_connected):
    intent = {"type": "shell_command", "confidence": 0.5, "raw_input": "run npm install"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_code_task_dispatches_to_platform(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "refactor the auth module"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.PLATFORM
    assert result.capability is not None


def test_knowledge_query_dispatches_to_platform(strategy_connected):
    intent = {"type": "knowledge_query", "confidence": 0.5, "raw_input": "what does the Bridge do?"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.PLATFORM


def test_code_task_falls_back_local_when_offline(strategy_offline):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "refactor the auth module"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_knowledge_query_falls_back_local_when_offline(strategy_offline):
    intent = {"type": "knowledge_query", "confidence": 0.5, "raw_input": "what does the Bridge do?"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_low_confidence_escalates_to_claude(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.15, "raw_input": "do something complex"}
    result = strategy_connected.decide(intent)
    assert result.target == DispatchTarget.CLAUDE


def test_low_confidence_offline_stays_local(strategy_offline):
    intent = {"type": "code_task", "confidence": 0.15, "raw_input": "do something complex"}
    result = strategy_offline.decide(intent)
    assert result.target == DispatchTarget.LOCAL


def test_decide_returns_capability_for_code_task(strategy_connected):
    intent = {"type": "code_task", "confidence": 0.6, "raw_input": "review this code"}
    result = strategy_connected.decide(intent)
    assert result.capability in ("code_review", "code_generation", "refactoring")


def test_decide_returns_reason(strategy_connected):
    intent = {"type": "file_operation", "confidence": 0.6, "raw_input": "read config.py"}
    result = strategy_connected.decide(intent)
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0
