"""Tests for StateSyncChannel — event broadcasting and queuing."""

import pytest
from archie_engine.state_sync import StateSyncChannel, SyncEvent


@pytest.fixture
def sync():
    return StateSyncChannel()


def test_emit_event(sync):
    sync.emit(SyncEvent(kind="file_changed", data={"file": "test.py", "action": "edit"}))
    assert len(sync.event_log) == 1
    assert sync.event_log[0].kind == "file_changed"


def test_emit_multiple_events(sync):
    sync.emit(SyncEvent(kind="file_changed", data={"file": "a.py", "action": "edit"}))
    sync.emit(SyncEvent(kind="git_commit", data={"branch": "main", "sha": "abc1234"}))
    assert len(sync.event_log) == 2
    assert sync.event_log[0].kind == "file_changed"
    assert sync.event_log[1].kind == "git_commit"


def test_get_pending_events(sync):
    sync.emit(SyncEvent(kind="file_changed", data={"file": "a.py", "action": "edit"}))
    sync.emit(SyncEvent(kind="task_started", data={"task": "review code"}))
    pending = sync.get_pending()
    assert len(pending) == 2
    assert len(sync.get_pending()) == 0


def test_conflict_detection_same_file(sync):
    sync.emit(SyncEvent(kind="file_changed", data={"file": "config.py", "action": "edit", "source": "archie"}))
    conflicts = sync.check_conflicts(
        SyncEvent(kind="file_changed", data={"file": "config.py", "action": "edit", "source": "claude"})
    )
    assert len(conflicts) == 1
    assert "config.py" in conflicts[0]


def test_no_conflict_different_files(sync):
    sync.emit(SyncEvent(kind="file_changed", data={"file": "a.py", "action": "edit", "source": "archie"}))
    conflicts = sync.check_conflicts(
        SyncEvent(kind="file_changed", data={"file": "b.py", "action": "edit", "source": "claude"})
    )
    assert len(conflicts) == 0


def test_event_to_dict(sync):
    event = SyncEvent(kind="file_changed", data={"file": "test.py"})
    d = event.to_dict()
    assert d["kind"] == "file_changed"
    assert d["data"]["file"] == "test.py"
    assert "timestamp" in d


def test_event_log_max_size(sync):
    for i in range(1500):
        sync.emit(SyncEvent(kind="tick", data={"i": i}))
    assert len(sync.event_log) <= 1000


def test_queue_events_when_offline(sync):
    sync.set_connected(False)
    sync.emit(SyncEvent(kind="file_changed", data={"file": "a.py"}))
    sync.emit(SyncEvent(kind="git_commit", data={"sha": "abc"}))
    assert len(sync.offline_queue) == 2
    sync.set_connected(True)
    drained = sync.drain_offline_queue()
    assert len(drained) == 2
    assert len(sync.offline_queue) == 0
