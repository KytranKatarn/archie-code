"""Skill registry — discover, load, and execute skills."""

import logging
from pathlib import Path
from archie_engine.skills.loader import SkillLoader
from archie_engine.skills.skill import Skill
from archie_engine.skills.executor import SkillExecutor

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, skill_dirs: list[Path], executor: SkillExecutor):
        self.loader = SkillLoader(skill_dirs)
        self.executor = executor
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        """Load all skills from configured directories."""
        skills = self.loader.load_all()
        self._skills = {s.name: s for s in skills}
        logger.info("Loaded %d skills", len(self._skills))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [s.to_dict() for s in self._skills.values()]

    async def execute(self, name: str, args: dict, context: dict | None = None) -> dict:
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "response": f"Skill not found: {name}"}
        return await self.executor.execute(skill, args=args, context=context)

    @staticmethod
    def parse_command(text: str) -> tuple[str, str]:
        """Parse '/command args' into (command_name, raw_args)."""
        text = text.strip()
        if not text.startswith("/"):
            return ("", text)
        parts = text[1:].split(None, 1)
        name = parts[0] if parts else ""
        raw_args = parts[1] if len(parts) > 1 else ""
        return (name, raw_args)
