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
#
# ⚠️ EVERY VALUE HERE MUST BE A CAPABILITY THE PLATFORM ACTUALLY KNOWS.
# A capability string is a REFERENCE, not a label: the platform resolves it through
# CAPABILITY_DEPARTMENT_MAP to a department, then selects an agent by matching it
# against agent_skills.skill_name. A string in NEITHER is not "a custom capability" —
# it is a dead reference. Unmapped falls back to the Engineering default, and because
# the scorer applies a -1.0 HARD PENALTY when a capability is requested and the
# candidate does not hold it as a skill, the work lands on whichever agent scores
# least badly rather than on anyone who can do it.
#
# Measured on the live platform 2026-09-11 — THREE of the five strings this module
# could emit were dead references, unmapped AND held by ZERO agents:
#     knowledge_search -> unmapped, 0 agents    (now: research, 8 agents, R&D)
#     code_generation  -> unmapped, 0 agents    (now: code, 4 agents, Engineering)
#     refactoring      -> unmapped, 0 agents    (now: code)
# Only "general" (2 agents) and "code_review" (3 agents) resolved. Near-miss worth
# knowing: "code-generation" WITH A HYPHEN does exist on 2 agents, which is most
# likely how the underscored typo survived review.
#
# Same defect class as the platform's own `auto_document` bug (KB #261742) and the
# 'news' residency profile that did not exist (KB #300145): a name in a constant that
# nothing ever asserts resolves.
#
# ⛔ Do NOT add a value here without checking it against BOTH platform sources:
#     CAPABILITY_DEPARTMENT_MAP  (services/department_coordinator.py)
#     agent_skills.skill_name    (at least one non-decommissioned agent)
# tests/test_engine_capability_resolution.py pins this so a new dead reference fails a
# test instead of silently misrouting for months.
LLM_INTENTS = {
    "conversation": "general",
    "knowledge_query": "research",
    "code_task": "code",
}

# The COMPLETE set this module can emit, including every _resolve_capability branch.
# Kept beside LLM_INTENTS deliberately: one list for the test to check, so there is no
# second list to fall out of step with this one.
EMITTED_CAPABILITIES = frozenset({"general", "research", "code", "code_review"})

# Confidence below this triggers Claude escalation (when hub is available)
ESCALATION_THRESHOLD = 0.2


class DispatchStrategy:
    """Decide where to route each intent: local engine, platform Bridge, or Claude."""

    def __init__(self, hub_available: bool = False, local_only: bool = True):
        self.hub_available = hub_available
        # Strictly-local (ADR-003, decision #4): when True, never escalate to
        # CLAUDE/cloud — LLM work routes to PLATFORM (DHQ local cluster) or, when
        # the hub is offline, direct-Ollama fallback.
        self.local_only = local_only

    def decide(self, intent: dict) -> DispatchDecision:
        """Return a DispatchDecision for the given classified intent."""
        intent_type = intent.get("type", "conversation")
        confidence = intent.get("confidence", 0.2)
        raw_input = intent.get("raw_input", "")

        # Low confidence + hub available → escalate to Claude (cloud).
        # Suppressed under strictly-local (ADR-003, decision #4): fall through to
        # PLATFORM (DHQ local cluster) rather than reaching for paid cloud.
        if confidence < ESCALATION_THRESHOLD and self.hub_available and not self.local_only:
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
        # Refactoring is an EDIT, not an audit, so it wants the coder bench rather
        # than a review capability. It used to return "refactoring", which no agent
        # holds — see the LLM_INTENTS note above. "code" is the real capability with
        # the deepest bench (4 agents), and F.O.R.G.E. holds it at Lv5.
        if any(kw in lower for kw in ("refactor", "clean", "simplify")):
            return "code"
        return base
