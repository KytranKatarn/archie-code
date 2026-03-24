"""Escalation logic — detect when to suggest Claude involvement."""

import logging

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.4
FAILURE_THRESHOLD = 2
COMPLEXITY_FILE_THRESHOLD = 4


class EscalationDetector:
    def should_escalate(self, intent: dict, failure_count: int = 0,
                        context: dict | None = None, user_requested: bool = False) -> dict:
        if user_requested:
            return {"escalate": True, "reason": "User requested Claude assistance"}
        confidence = intent.get("confidence", 1.0)
        if confidence < CONFIDENCE_THRESHOLD:
            return {"escalate": True, "reason": f"Low confidence ({confidence:.1f}) on intent classification"}
        if failure_count >= FAILURE_THRESHOLD:
            return {"escalate": True, "reason": f"Repeated failures ({failure_count}) on this task"}
        intent_type = intent.get("type", "")
        if intent_type == "code_task" and context:
            files = context.get("files_involved", [])
            if len(files) >= COMPLEXITY_FILE_THRESHOLD:
                return {"escalate": True, "reason": f"Complex task spanning {len(files)} files"}
        return {"escalate": False, "reason": ""}
