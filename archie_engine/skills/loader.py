"""Skill loader — discover and load skill files from directories."""

import logging
from pathlib import Path
from archie_engine.skills.skill import Skill, is_invocable_skill, parse_skill

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, skill_dirs: list[Path]):
        self.skill_dirs = skill_dirs

    def load_all(self) -> list[Skill]:
        """Load every INVOCABLE .md skill from the configured directories.

        The glob is `**/*.md` over dirs that include the hub-synced skills
        cache, which also holds GitHub-ingested REFERENCE DOCS. Those parse as
        perfectly valid markdown with a frontmatter `name:`, so the old
        `if skill.name` check admitted all of them: the TUI's `/` palette
        listed 188 entries of which 6 were real skills and 182 were documents
        like `CONTRIBUTING.md` and `.claude-plugin/marketplace.json`.

        `is_invocable_skill` is the contract. Rejections are COUNTED and
        logged -- a filter that silently drops things is how a real skill
        would go missing without anyone noticing.
        """
        skills = []
        rejected = 0
        for directory in self.skill_dirs:
            if not directory.exists():
                continue
            source = directory.name
            for md_file in sorted(directory.glob("**/*.md")):
                try:
                    raw = md_file.read_text()
                    skill = parse_skill(raw, source=source, file_path=str(md_file))
                    if not skill.name:
                        continue
                    if not is_invocable_skill(skill):
                        rejected += 1
                        logger.debug(
                            "Skipping non-invocable entry %s (name=%r)",
                            md_file, skill.name,
                        )
                        continue
                    skills.append(skill)
                except Exception as e:
                    logger.warning("Failed to load skill %s: %s", md_file, e)
        if rejected:
            logger.info(
                "Skill registry: %d invocable skill(s); skipped %d reference doc(s)",
                len(skills), rejected,
            )
        return skills
