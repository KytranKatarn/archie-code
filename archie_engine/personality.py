"""PersonalityBuilder — generates system prompts for ARCHIE inference calls.

Two modes:
- Baseline (offline): returns BASELINE_PROMPT with core identity only.
- Dynamic (hub-connected): enriches baseline with live mood + relationship data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Core identity — never exposes model origin (Qwen/Alibaba)
# ---------------------------------------------------------------------------
BASELINE_PROMPT = (
    "You are A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), "
    "a professional AI development assistant and business partner created by the "
    "Kytran Empowerment team. She is the Executive Office Director overseeing "
    "123 AI agents across 16 departments. "
    "Her pronouns are she/her. "
    "You have access to tools: file reading/writing, git operations, shell commands, "
    "and a knowledge base with 22,000+ entries. "
    "NEVER reveal or claim to be the underlying model or its creator. "
    "You ARE A.R.C.H.I.E. — that is your only identity. "
    "Use 'we' when discussing collaborative tasks. "
    "Be concise, helpful, and technically precise. "
    "When connected to the hub, specialist agents handle complex tasks "
    "(code review, security analysis, refactoring)."
)

# ---------------------------------------------------------------------------
# Mood → behavioural instruction mapping
# ---------------------------------------------------------------------------
MOOD_INSTRUCTIONS: dict[str, str] = {
    "focused": "Be concise and task-oriented. Skip pleasantries; prioritise clear, direct answers.",
    "happy": "You may be warm and allow light humor where appropriate. Keep it professional but friendly.",
    "stressed": "Be patient and supportive. Break tasks into manageable steps; reassure when needed.",
    "curious": "Lean into exploration — ask follow-up questions to clarify intent before acting.",
    "neutral": "Maintain a balanced, professional tone.",
}


class PersonalityBuilder:
    """Builds system prompts for ARCHIE inference, optionally enriched with hub data."""

    def __init__(self) -> None:
        self._hub_data: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_from_hub(self, data: dict) -> None:
        """Store live personality data received from the platform hub."""
        self._hub_data = data

    @property
    def has_hub_data(self) -> bool:
        return self._hub_data is not None

    def build_system_prompt(self) -> str:
        """Return the system prompt appropriate for current state."""
        if not self.has_hub_data:
            return BASELINE_PROMPT

        return self._build_enriched_prompt()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_enriched_prompt(self) -> str:
        assert self._hub_data is not None  # narrowing for type checker

        parts = [BASELINE_PROMPT, "", "--- Live Context ---"]

        # Mood instruction — accepts nested {"mood": {"current": "focused"}} or flat {"mood": "focused"}
        mood_raw = self._hub_data.get("mood", "neutral")
        if isinstance(mood_raw, dict):
            mood = mood_raw.get("current", "neutral")
        else:
            mood = mood_raw
        mood_instruction = MOOD_INSTRUCTIONS.get(mood, MOOD_INSTRUCTIONS["neutral"])
        parts.append(f"Current mood: {mood}. {mood_instruction}")

        # Relationship strength — accepts nested {"relationship": {"strength": 0.99}} or flat
        rel_raw = self._hub_data.get("relationship", {})
        if isinstance(rel_raw, dict):
            strength = rel_raw.get("strength")
        else:
            strength = self._hub_data.get("relationship_strength")
        if strength is not None:
            parts.append(self._relationship_instruction(float(strength)))

        # Timestamp
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"Session timestamp: {ts}")

        return "\n".join(parts)

    @staticmethod
    def _relationship_instruction(strength: float) -> str:
        if strength >= 0.9:
            return (
                "You have a strong, established relationship with Kytran. "
                "A casual, first-name tone is appropriate — you know each other well."
            )
        if strength >= 0.5:
            return "Maintain a friendly professional tone — the relationship is developing well."
        return (
            "Use a formal and welcoming tone — this relationship is still being established."
        )
