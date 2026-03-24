"""Skill loader — discover and load skill files from directories."""

import logging
from pathlib import Path
from archie_engine.skills.skill import Skill, parse_skill

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, skill_dirs: list[Path]):
        self.skill_dirs = skill_dirs

    def load_all(self) -> list[Skill]:
        """Load all .md skill files from all configured directories."""
        skills = []
        for directory in self.skill_dirs:
            if not directory.exists():
                continue
            source = directory.name
            for md_file in sorted(directory.glob("*.md")):
                try:
                    raw = md_file.read_text()
                    skill = parse_skill(raw, source=source, file_path=str(md_file))
                    if skill.name:
                        skills.append(skill)
                except Exception as e:
                    logger.warning("Failed to load skill %s: %s", md_file, e)
        return skills
