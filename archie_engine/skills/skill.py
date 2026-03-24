"""Skill dataclass — parsed from markdown with YAML frontmatter."""

import re
import yaml
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str = ""
    description: str = ""
    arguments: list[dict] = field(default_factory=list)
    body: str = ""
    source: str = "community"
    file_path: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
            "source": self.source,
        }


def parse_skill(raw: str, source: str = "community", file_path: str = "") -> Skill:
    """Parse a skill markdown file with optional YAML frontmatter."""
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)

    if not frontmatter_match:
        return Skill(body=raw.strip(), source=source, file_path=file_path)

    try:
        meta = yaml.safe_load(frontmatter_match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}

    body = frontmatter_match.group(2).strip()

    return Skill(
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        arguments=meta.get("arguments", []),
        body=body,
        source=source,
        file_path=file_path,
    )
