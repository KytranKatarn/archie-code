"""State sync channel — broadcasts file/git/task events for Claude collaboration."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import deque

logger = logging.getLogger(__name__)

MAX_EVENT_LOG = 1000
CONFLICT_WINDOW_SECONDS = 30


@dataclass
class SyncEvent:
    kind: str
    data: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {"kind": self.kind, "data": self.data, "timestamp": self.timestamp}


class StateSyncChannel:
    def __init__(self):
        self.event_log: deque[SyncEvent] = deque(maxlen=MAX_EVENT_LOG)
        self._pending: list[SyncEvent] = []
        self.offline_queue: list[SyncEvent] = []
        self._connected = True

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def emit(self, event: SyncEvent) -> None:
        self.event_log.append(event)
        if self._connected:
            self._pending.append(event)
        else:
            self.offline_queue.append(event)

    def get_pending(self) -> list[SyncEvent]:
        events = list(self._pending)
        self._pending.clear()
        return events

    def drain_offline_queue(self) -> list[SyncEvent]:
        events = list(self.offline_queue)
        self.offline_queue.clear()
        return events

    def check_conflicts(self, incoming: SyncEvent) -> list[str]:
        conflicts = []
        if incoming.kind != "file_changed":
            return conflicts

        incoming_file = incoming.data.get("file", "")
        incoming_source = incoming.data.get("source", "")
        incoming_ts = datetime.fromisoformat(incoming.timestamp)

        for event in reversed(self.event_log):
            if event.kind != "file_changed":
                continue
            event_file = event.data.get("file", "")
            event_source = event.data.get("source", "")
            if event_file != incoming_file:
                continue
            if event_source == incoming_source:
                continue
            event_ts = datetime.fromisoformat(event.timestamp)
            delta = abs((incoming_ts - event_ts).total_seconds())
            if delta <= CONFLICT_WINDOW_SECONDS:
                conflicts.append(
                    f"Conflict: {incoming_file} edited by both {event_source} and {incoming_source} within {delta:.0f}s"
                )
                break

        return conflicts
