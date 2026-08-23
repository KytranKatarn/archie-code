"""Skill dataclass — parsed from markdown with YAML frontmatter."""

import re
import yaml
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# Frontmatter keys written ONLY by the hub's GitHub-ingest pipeline. Their
# presence marks a CATALOG REFERENCE DOC (searchable via search_knowledge), not
# an executable skill. `.claude/rules/learned-skills.md` says so explicitly.
_INGEST_ONLY_KEYS = ("source_repo", "installed_from", "quality_score")


@dataclass
class Skill:
    name: str = ""
    description: str = ""
    arguments: list[dict] = field(default_factory=list)
    body: str = ""
    source: str = "community"
    file_path: str = ""
    # Raw frontmatter, retained so the loader can apply the invocability
    # contract below. Deliberately NOT exposed by to_dict().
    meta: dict = field(default_factory=dict)

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
        meta=meta,
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        arguments=meta.get("arguments", []),
        body=body,
        source=source,
        file_path=file_path,
    )


def has_invocable_name(name) -> bool:
    """A skill's name IS its invocation handle -- you type ``/commit``.

    So a name you could not type is not a skill name. This rejects the
    path-shaped names the ingest pipeline writes, e.g.
    ``skills/writing-skills/references/tier-1-simple/README.md``.
    """
    if not name or not isinstance(name, str):
        return False
    if any(ch in name for ch in "/\\ \t"):
        return False
    # README.md, marketplace.json, package_skill.py -- a document, not a skill.
    return not PurePosixPath(name).suffix


def is_reference_doc(meta: dict) -> bool:
    """True when frontmatter carries the hub ingest pipeline's provenance keys."""
    return isinstance(meta, dict) and any(k in meta for k in _INGEST_ONLY_KEYS)


def is_invocable_skill(skill: "Skill") -> bool:
    """The registry contract: an executable skill, not an ingested document.

    BOTH checks are load-bearing and neither is sufficient alone -- measured
    against the live corpus (6 real community skills + 182 hub-cache files):

    * name-only  -> keeps 6/6 real, but 24 of the 182 leak through, because
      docs like ``karpathy-hn-time-capsule`` carry bare, skill-shaped names.
    * provenance-only -> a clean 182/182 vs 0/6 split TODAY, but it trusts the
      ingest to keep writing those keys.

    Together they are belt-and-braces: if the ingest drops its provenance keys
    the name check still rejects the 158 path-named files, and if a bare-named
    document is ingested the provenance check still rejects it.
    """
    return has_invocable_name(skill.name) and not is_reference_doc(skill.meta)
