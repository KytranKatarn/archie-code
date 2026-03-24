import pytest
import json
from archie_engine.claude.context_bridge import ContextBridge


@pytest.fixture
def bridge():
    return ContextBridge(working_dir="/tmp/myproject")


def test_build_context_has_required_fields(bridge):
    ctx = bridge.build_context(task="Fix auth bug", files=["auth.py", "rbac.py"])
    assert ctx["task"] == "Fix auth bug"
    assert ctx["working_dir"] == "/tmp/myproject"
    assert "auth.py" in ctx["files_involved"]


def test_build_context_with_intent(bridge):
    ctx = bridge.build_context(task="Fix auth bug", intent={"type": "code_task", "confidence": 0.9})
    assert ctx["intent"]["type"] == "code_task"


def test_build_context_with_kb_context(bridge):
    ctx = bridge.build_context(task="Fix auth bug", kb_entries=[{"content": "Auth uses JWT tokens", "importance": 0.9}])
    assert len(ctx["kb_context"]) == 1


def test_build_context_with_history(bridge):
    ctx = bridge.build_context(task="Fix", history=[{"role": "user", "content": "fix"}, {"role": "assistant", "content": "ok"}])
    assert len(ctx["history"]) == 2


def test_to_markdown(bridge):
    ctx = bridge.build_context(task="Fix auth bug", files=["auth.py"])
    md = bridge.to_markdown(ctx)
    assert "Fix auth bug" in md
    assert "auth.py" in md


def test_to_json(bridge):
    ctx = bridge.build_context(task="Fix auth bug")
    j = bridge.to_json(ctx)
    parsed = json.loads(j)
    assert parsed["task"] == "Fix auth bug"
