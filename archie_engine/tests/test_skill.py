import pytest
from archie_engine.skills.skill import Skill, parse_skill


SAMPLE_SKILL = """---
name: commit
description: Create a git commit
arguments:
  - name: message
    description: Optional commit message
    required: false
---

Review staged changes and create a commit.

Steps:
1. Run git diff --staged
2. Generate commit message
3. Commit
"""


def test_parse_skill_name():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert skill.name == "commit"


def test_parse_skill_description():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert "git commit" in skill.description


def test_parse_skill_arguments():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert len(skill.arguments) == 1
    assert skill.arguments[0]["name"] == "message"
    assert skill.arguments[0]["required"] is False


def test_parse_skill_body():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert "Review staged changes" in skill.body
    assert "Steps:" in skill.body


def test_parse_skill_source():
    skill = parse_skill(SAMPLE_SKILL, source="hub")
    assert skill.source == "hub"


def test_parse_skill_no_frontmatter():
    raw = "Just a plain markdown file with no frontmatter."
    skill = parse_skill(raw, source="custom")
    assert skill.name == ""
    assert skill.body == raw


def test_skill_to_dict():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    d = skill.to_dict()
    assert d["name"] == "commit"
    assert "arguments" in d
