"""Learning store — captures escalation resolutions for future reuse."""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.6
MAX_FAILURES = 2


class LearningStore:
    def __init__(self, data_dir: Path):
        self._file = data_dir / "learnings.json"
        self._learnings: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._file.exists():
            try:
                self._learnings = json.loads(self._file.read_text())
            except (json.JSONDecodeError, OSError):
                self._learnings = []

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(self._learnings, indent=2))

    def record(self, intent_type: str, task_summary: str,
               resolution: str, source: str) -> None:
        self._learnings.append({
            "intent_type": intent_type,
            "task_summary": task_summary,
            "resolution": resolution,
            "source": source,
            "failure_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save()

    def find_match(self, intent_type: str, task_summary: str) -> dict | None:
        for learning in self._learnings:
            if learning["intent_type"] != intent_type:
                continue
            if learning["failure_count"] >= MAX_FAILURES:
                continue
            similarity = SequenceMatcher(
                None, learning["task_summary"].lower(), task_summary.lower()
            ).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                return learning
        return None

    def mark_failure(self, task_summary: str) -> None:
        for learning in self._learnings:
            similarity = SequenceMatcher(
                None, learning["task_summary"].lower(), task_summary.lower()
            ).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                learning["failure_count"] += 1
                self._save()
                return

    def get_all(self) -> list[dict]:
        return list(self._learnings)

    def to_kb_format(self, learning: dict) -> dict:
        return {
            "knowledge_type": "mistake_learned" if learning["failure_count"] > 0 else "vault_note",
            "title": f"Learned: {learning['task_summary'][:80]}",
            "content": (
                f"Intent: {learning['intent_type']}\n"
                f"Task: {learning['task_summary']}\n"
                f"Resolution: {learning['resolution']}\n"
                f"Source: {learning['source']}\n"
                f"Learned: {learning['created_at']}"
            ),
            "category": "escalation_learning",
        }
