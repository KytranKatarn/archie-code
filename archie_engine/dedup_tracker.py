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
# #6057: the cooldown THROTTLES re-attempts but never stops them -- PRs #2857/#2865
# were byte-identical builds one cooldown apart from a finding no fix could land on.
# A merged fix closes its issue via the hub reconciler/scanner, so the only keys that
# ever accumulate attempts are ones whose PRs did NOT land: cap them permanently.
DEFAULT_MAX_ATTEMPTS = 2


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
                    # Legacy format was {key: float_ts}; migrate to {count, last} so
                    # pre-#6057 history survives (as one attempt) instead of resetting.
                    self._attempts = {
                        k: (v if isinstance(v, dict) else {"count": 1, "last": float(v)})
                        for k, v in data.items()
                    }
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                self._attempts = {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._attempts))
        except OSError as e:
            logger.warning("DedupTracker save failed: %s", e)

    def should_skip(self, issue_id, cooldown_sec: int = DEFAULT_COOLDOWN_SEC,
                    max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> bool:
        """True if attempted within the cooldown window, OR capped (#6057).

        The cap is PERMANENT: once ``max_attempts`` builds have been recorded for a
        key, cooldown expiry no longer revives it. ``max_attempts`` <= 0 or None
        disables the cap (cooldown-only, the pre-#6057 behaviour).
        """
        if issue_id is None:
            return False
        entry = self._attempts.get(str(issue_id))
        if entry is None:
            return False
        if max_attempts and entry.get("count", 0) >= max_attempts:
            return True
        last = entry.get("last", 0)
        return (time.time() - last) < cooldown_sec

    def record(self, issue_id) -> None:
        """Stamp an attempt at the current time and bump the attempt count."""
        if issue_id is None:
            return
        key = str(issue_id)
        entry = self._attempts.get(key) or {"count": 0, "last": 0.0}
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last"] = time.time()
        self._attempts[key] = entry
        if entry["count"] == DEFAULT_MAX_ATTEMPTS:
            logger.info("DedupTracker: %s reached %d attempts -- permanently skipped "
                        "unless the hub closes or re-files the finding (#6057)", key, entry["count"])
        self._save()
