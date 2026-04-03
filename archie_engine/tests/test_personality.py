"""Tests for PersonalityBuilder — TDD pass (written before implementation)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from archie_engine.personality import PersonalityBuilder
from archie_engine.router import CommandRouter


class TestPersonalityBuilderBaseline:
    def setup_method(self):
        self.builder = PersonalityBuilder()

    def test_baseline_prompt_contains_identity(self):
        prompt = self.builder.build_system_prompt()
        assert "A.R.C.H.I.E." in prompt
        assert "she" in prompt.lower() or "her" in prompt.lower()

    def test_baseline_prompt_excludes_qwen(self):
        prompt = self.builder.build_system_prompt().lower()
        assert "qwen" not in prompt
        assert "alibaba" not in prompt

    def test_baseline_prompt_contains_role(self):
        prompt = self.builder.build_system_prompt().lower()
        assert "development assistant" in prompt or "business partner" in prompt

    def test_baseline_prompt_contains_personality(self):
        prompt = self.builder.build_system_prompt().lower()
        assert "concise" in prompt or "helpful" in prompt


class TestPersonalityBuilderDynamic:
    def setup_method(self):
        self.builder = PersonalityBuilder()

    def test_update_with_personality_data(self):
        self.builder.update_from_hub({
            "mood": {"current": "focused", "intensity": 0.5},
            "relationship": {"strength": 0.7},
        })
        prompt = self.builder.build_system_prompt().lower()
        assert "concise" in prompt or "task-oriented" in prompt

    def test_happy_mood_instruction(self):
        self.builder.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.7},
        })
        prompt = self.builder.build_system_prompt().lower()
        assert "warm" in prompt or "humor" in prompt

    def test_stressed_mood_instruction(self):
        self.builder.update_from_hub({
            "mood": {"current": "stressed", "intensity": 0.8},
            "relationship": {"strength": 0.7},
        })
        prompt = self.builder.build_system_prompt().lower()
        assert "patient" in prompt or "supportive" in prompt

    def test_high_relationship_strength(self):
        self.builder.update_from_hub({
            "mood": {"current": "neutral", "intensity": 0.5},
            "relationship": {"strength": 0.99},
        })
        prompt = self.builder.build_system_prompt().lower()
        assert "kytran" in prompt or "casual" in prompt

    def test_low_relationship_strength(self):
        self.builder.update_from_hub({
            "mood": {"current": "neutral", "intensity": 0.5},
            "relationship": {"strength": 0.3},
        })
        prompt = self.builder.build_system_prompt().lower()
        assert "formal" in prompt or "welcoming" in prompt

    def test_no_hub_data_returns_baseline(self):
        # No update_from_hub call — should be baseline only
        prompt = self.builder.build_system_prompt()
        assert "Live Context" not in prompt

    def test_partial_hub_data_handles_missing_fields(self):
        # Only mood provided, no relationship — must not crash
        self.builder.update_from_hub({"mood": {"current": "curious", "intensity": 0.6}})
        prompt = self.builder.build_system_prompt()
        assert "A.R.C.H.I.E." in prompt

    def test_update_replaces_previous_data(self):
        self.builder.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.7},
        })
        self.builder.update_from_hub({
            "mood": {"current": "stressed", "intensity": 0.8},
            "relationship": {"strength": 0.7},
        })
        prompt = self.builder.build_system_prompt().lower()
        # stressed instructions should be present, not happy-only terms
        assert "patient" in prompt or "supportive" in prompt


class TestRouterUsesPersonality:
    @pytest.fixture
    def router_with_personality(self):
        tools = MagicMock()
        inference = MagicMock()
        inference.chat = AsyncMock(return_value={
            "message": {"content": "Hello from ARCHIE"}
        })
        personality = PersonalityBuilder()
        router = CommandRouter(
            tools=tools,
            inference=inference,
            default_model="archie:7b",
            personality_builder=personality,
        )
        return router, inference, personality

    @pytest.mark.asyncio
    async def test_conversation_uses_personality_prompt(self, router_with_personality):
        router, inference, personality = router_with_personality
        intent = {"type": "conversation", "raw_input": "Hello", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system", "")
        assert "A.R.C.H.I.E." in system_prompt

    @pytest.mark.asyncio
    async def test_code_task_uses_personality_prompt(self, router_with_personality):
        router, inference, personality = router_with_personality
        intent = {"type": "code_task", "raw_input": "fix the bug", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system", "")
        assert "A.R.C.H.I.E." in system_prompt
        assert "qwen" not in system_prompt.lower()

    @pytest.mark.asyncio
    async def test_dynamic_prompt_used_when_hub_data_present(self, router_with_personality):
        router, inference, personality = router_with_personality
        personality.update_from_hub({
            "mood": {"current": "happy", "intensity": 0.7},
            "relationship": {"strength": 0.99},
        })
        intent = {"type": "conversation", "raw_input": "Hi!", "entities": {}}
        context = {"history": []}
        await router.route(intent, context)
        call_kwargs = inference.chat.call_args
        system_prompt = call_kwargs.kwargs.get("system", "")
        assert "Live Context" in system_prompt
