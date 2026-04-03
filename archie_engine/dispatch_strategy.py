"""Dispatch strategy — decides local vs platform vs Claude for each intent."""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DispatchTarget(Enum):
    LOCAL = "local"
    PLATFORM = "platform"
    CLAUDE = "claude"


@dataclass
class DispatchDecision:
    target: DispatchTarget
    reason: str
    capability: str | None = None


# Tool-only intents — always local, no LLM needed
TOOL_INTENTS = {"file_operation", "git_operation", "shell_command"}

# LLM intents — route through Bridge when hub connected (agent-safe VRAM management)
# Direct Ollama ONLY when hub is offline (Community tier / disconnected)
LLM_INTENTS = {
    "conversation": "general",
    "knowledge_query": "knowledge_search",
    "code_task": "code_generation",
}

# Confidence below this triggers Claude escalation (when hub is available)
ESCALATION_THRESHOLD = 0.2


class DispatchStrategy:
    """Decide where to route each intent: local engine, platform Bridge, or Claude."""

    def __init__(self, hub_available: bool = False):
        self.hub_available = hub_available

    def decide(self, intent: dict) -> DispatchDecision:
        """Return a DispatchDecision for the given classified intent."""
        intent_type = intent.get("type", "conversation")
        confidence = intent.get("confidence", 0.2)
        raw_input = intent.get("raw_input", "")

        # Low confidence + hub available → escalate to Claude
        if confidence < ESCALATION_THRESHOLD and self.hub_available:
            return DispatchDecision(
                target=DispatchTarget.CLAUDE,
                reason=f"Low confidence ({confidence:.2f}) — escalating to Claude",
                capability=None,
            )

        # Tool-only intents — always local, no LLM needed
        if intent_type in TOOL_INTENTS:
            return DispatchDecision(
                target=DispatchTarget.LOCAL,
                reason=f"Tool intent '{intent_type}' — handled locally (no LLM)",
            )

        # LLM intents — route through Bridge when hub connected
        # This ensures agents are properly assigned, VRAM managed, no model collisions
        if intent_type in LLM_INTENTS:
            capability = self._resolve_capability(intent_type, raw_input)
            if self.hub_available:
                return DispatchDecision(
                    target=DispatchTarget.PLATFORM,
                    reason=f"LLM intent '{intent_type}' → Bridge (agent-safe dispatch)",
                    capability=capability,
                )
            # Hub offline → direct Ollama fallback
            return DispatchDecision(
                target=DispatchTarget.LOCAL,
                reason=f"Hub offline — handling '{intent_type}' via direct Ollama",
                capability=capability,
            )

        # Unknown intent type → local fallback
        return DispatchDecision(
            target=DispatchTarget.LOCAL,
            reason=f"Unknown intent '{intent_type}' — local fallback",
        )

    def _resolve_capability(self, intent_type: str, raw_input: str) -> str:
        """Map intent + raw input to a specific agent capability string."""
        base = LLM_INTENTS.get(intent_type, "general")
        if intent_type != "code_task":
            return base

        lower = raw_input.lower()
        if any(kw in lower for kw in ("review", "audit", "check")):
            return "code_review"
        if any(kw in lower for kw in ("refactor", "clean", "simplify")):
            return "refactoring"
        return "code_generation"
