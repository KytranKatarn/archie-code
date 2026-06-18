"""Engine-local dedup for autonomous pull-work (#380).

Remembers recently-attempted Repair-Bay issue ids so the autonomous scheduler
ROTATES through findings instead of hammering the same highest-severity one every
cycle (and re-opening duplicate PRs). JSON-backed in the engine data dir; best-effort
(a load/save failure must never break a build).
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SEC = 21600  # 6h


class DedupTracker:
    def __init__(self, data_dir):
        self._file = Path(data_dir) / "attempted_issues.json"
        self._attempts: dict = {}
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                if isinstance(data, dict):
                    self._attempts = data
            except (json.JSONDecodeError, OSError):
                self._attempts = {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._attempts))
        except OSError as e:
            logger.warning("DedupTracker save failed: %s", e)

    def should_skip(self, issue_id, cooldown_sec: int = DEFAULT_COOLDOWN_SEC) -> bool:
        """True if this issue was attempted within the cooldown window."""
        if issue_id is None:
            return False
        ts = self._attempts.get(str(issue_id))
        return ts is not None and (time.time() - ts) < cooldown_sec

    def record(self, issue_id) -> None:
        """Stamp an attempt at the current time."""
        if issue_id is None:
            return
        self._attempts[str(issue_id)] = time.time()
        self._save()
