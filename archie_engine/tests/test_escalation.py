import pytest
from archie_engine.claude.escalation import EscalationDetector


@pytest.fixture
def detector():
    return EscalationDetector()


def test_no_escalation_simple(detector):
    result = detector.should_escalate(intent={"type": "file_operation", "confidence": 0.9}, failure_count=0)
    assert not result["escalate"]


def test_escalate_low_confidence(detector):
    result = detector.should_escalate(intent={"type": "code_task", "confidence": 0.3}, failure_count=0)
    assert result["escalate"]
    assert "confidence" in result["reason"].lower()


def test_escalate_repeated_failures(detector):
    result = detector.should_escalate(intent={"type": "code_task", "confidence": 0.8}, failure_count=3)
    assert result["escalate"]
    assert "failure" in result["reason"].lower()


def test_escalate_complex_task(detector):
    result = detector.should_escalate(
        intent={"type": "code_task", "confidence": 0.7}, failure_count=0,
        context={"files_involved": ["a.py", "b.py", "c.py", "d.py", "e.py"]})
    assert result["escalate"]
    assert "complex" in result["reason"].lower()


def test_no_escalate_conversation(detector):
    result = detector.should_escalate(intent={"type": "conversation", "confidence": 0.9}, failure_count=0)
    assert not result["escalate"]


def test_user_override(detector):
    result = detector.should_escalate(
        intent={"type": "file_operation", "confidence": 0.9}, failure_count=0, user_requested=True)
    assert result["escalate"]
    assert "user" in result["reason"].lower()
