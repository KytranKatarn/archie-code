"""Skill executor — renders skill templates and runs through inference."""

import logging
from archie_engine.skills.skill import Skill
from archie_engine.inference import InferenceClient
from archie_engine.tools import ToolRegistry

logger = logging.getLogger(__name__)


class SkillExecutor:
    def __init__(self, inference: InferenceClient, tools: ToolRegistry, default_model: str = "qwen2.5:7b"):
        self.inference = inference
        self.tools = tools
        self.default_model = default_model

    async def execute(self, skill: Skill, args: dict, context: dict | None = None) -> dict:
        """Execute a skill — render template, call inference."""
        rendered = self._render_template(skill.body, args)
        system = f"You are executing the /{skill.name} skill: {skill.description}"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": rendered},
        ]
        if context and context.get("history"):
            for msg in context["history"][-5:]:
                messages.insert(-1, {"role": msg["role"], "content": msg["content"]})

        try:
            result = await self.inference.chat(messages=messages, model=self.default_model)
            response = result.get("message", {}).get("content", "")
            return {
                "success": True,
                "response": response,
                "skill": skill.name,
                "model_used": result.get("model", self.default_model),
            }
        except Exception as e:
            logger.error("Skill %s execution failed: %s", skill.name, e)
            return {"success": False, "response": f"Skill error: {e}", "skill": skill.name}

    def _render_template(self, body: str, args: dict) -> str:
        """Simple template rendering — replace {{arg_name}} with values."""
        rendered = body
        for key, value in args.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        if args:
            rendered += "\n\nArguments provided:\n"
            for k, v in args.items():
                rendered += f"- {k}: {v}\n"
        return rendered
