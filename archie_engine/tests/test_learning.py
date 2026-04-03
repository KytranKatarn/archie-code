"""Tests for LearningStore — escalation pattern storage and retrieval."""

import pytest
from archie_engine.learning import LearningStore


@pytest.fixture
def store(tmp_path):
    return LearningStore(data_dir=tmp_path)


def test_store_learning(store):
    store.record(intent_type="code_task", task_summary="refactor auth module",
                 resolution="Split into auth_service.py and auth_routes.py", source="claude")
    assert len(store.get_all()) == 1


def test_find_matching_pattern(store):
    store.record(intent_type="code_task", task_summary="refactor auth module",
                 resolution="Split service from routes", source="claude")
    match = store.find_match(intent_type="code_task", task_summary="refactor the authentication module")
    assert match is not None
    assert "Split" in match["resolution"]


def test_no_match_different_type(store):
    store.record(intent_type="code_task", task_summary="refactor auth",
                 resolution="Split files", source="claude")
    match = store.find_match(intent_type="knowledge_query", task_summary="refactor auth")
    assert match is None


def test_stale_pattern_flagged(store):
    store.record(intent_type="code_task", task_summary="fix login bug",
                 resolution="Check session expiry", source="claude")
    store.mark_failure("fix login bug")
    match = store.find_match(intent_type="code_task", task_summary="fix login bug")
    assert match is not None  # Still returned after 1 failure
    store.mark_failure("fix login bug")
    match = store.find_match(intent_type="code_task", task_summary="fix login bug")
    assert match is None  # Stale after 2 failures


def test_persistence(tmp_path):
    store1 = LearningStore(data_dir=tmp_path)
    store1.record(intent_type="code_task", task_summary="optimize query",
                  resolution="Add index on user_id", source="platform")
    store2 = LearningStore(data_dir=tmp_path)
    assert len(store2.get_all()) == 1
    assert store2.get_all()[0]["resolution"] == "Add index on user_id"


def test_to_kb_format(store):
    store.record(intent_type="code_task", task_summary="fix CSS layout",
                 resolution="Use flexbox instead of float", source="claude")
    kb_entry = store.to_kb_format(store.get_all()[0])
    assert kb_entry["knowledge_type"] in ("mistake_learned", "vault_note")
    assert "flexbox" in kb_entry["content"]
