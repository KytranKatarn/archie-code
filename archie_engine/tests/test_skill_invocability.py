"""The skill-registry invocability contract (#5974).

The engine globs `**/*.md` over skill_dirs, which include the hub-synced
skills cache. That cache holds GitHub-ingested REFERENCE DOCS that parse as
valid skill markdown, so the TUI's `/` palette listed 188 entries of which
only 6 were real skills.
"""

from archie_engine.skills.skill import (
    has_invocable_name,
    is_invocable_skill,
    is_reference_doc,
    parse_skill,
)

REAL = """---
name: commit
description: Create a git commit
arguments:
  - name: message
    required: false
---
Create a git commit for the current staged changes.
"""

# Shape 1: path-shaped name. 158 of the 182 live cache files look like this.
DOC_PATH_NAME = """---
name: skills/writing-skills/references/tier-1-simple/README.md
description: When to use Tier 1 skill architecture.
source_repo: sickn33/antigravity-awesome-skills
quality_score: 4
---
# Tier 1: Simple Skills
"""

# Shape 2: BARE, skill-shaped name. 24 of the 182 look like this -- these are
# exactly the ones the name check alone cannot catch.
DOC_BARE_NAME = """---
name: karpathy-hn-time-capsule
description: A reference document with a name that looks like a skill.
source_repo: some/repo
installed_from: 256
---
# Not a skill
"""


def test_a_real_skill_is_invocable():
    assert is_invocable_skill(parse_skill(REAL)) is True


def test_path_shaped_name_is_rejected():
    assert is_invocable_skill(parse_skill(DOC_PATH_NAME)) is False


def test_bare_named_reference_doc_is_rejected():
    assert is_invocable_skill(parse_skill(DOC_BARE_NAME)) is False


def test_name_check_is_load_bearing():
    """Provenance alone would admit a path-named file that carries no ingest keys."""
    doc = parse_skill(
        "---\nname: skills/foo/README.md\ndescription: d\n---\nbody\n"
    )
    assert is_reference_doc(doc.meta) is False  # provenance check does NOT catch it
    assert has_invocable_name(doc.name) is False  # the name check does
    assert is_invocable_skill(doc) is False


def test_provenance_check_is_load_bearing():
    """The name check alone would admit DOC_BARE_NAME -- this is the 24-file leak."""
    doc = parse_skill(DOC_BARE_NAME)
    assert has_invocable_name(doc.name) is True  # name check does NOT catch it
    assert is_reference_doc(doc.meta) is True  # provenance does
    assert is_invocable_skill(doc) is False


def test_real_skill_names_all_pass():
    for name in ("commit", "debug", "explain", "refactor", "review", "test",
                 "deploy-website", "code_review"):
        assert has_invocable_name(name) is True, name


def test_non_invocable_names():
    for name in ("", None, "a/b", "README.md", "marketplace.json",
                 "package_skill.py", "two words"):
        assert has_invocable_name(name) is False, name
