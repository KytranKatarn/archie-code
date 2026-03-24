import pytest
from pathlib import Path
from archie_engine.skills.loader import SkillLoader


@pytest.fixture
def skill_dirs(tmp_path):
    community = tmp_path / "community"
    community.mkdir()
    (community / "commit.md").write_text("---\nname: commit\ndescription: Create commit\n---\nCommit stuff.")
    (community / "review.md").write_text("---\nname: review\ndescription: Review code\n---\nReview stuff.")

    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "deploy.md").write_text("---\nname: deploy\ndescription: Deploy app\n---\nDeploy stuff.")

    return [community, custom]


@pytest.fixture
def loader(skill_dirs):
    return SkillLoader(skill_dirs=skill_dirs)


def test_load_all_skills(loader):
    skills = loader.load_all()
    assert len(skills) == 3


def test_skill_names(loader):
    skills = loader.load_all()
    names = {s.name for s in skills}
    assert "commit" in names
    assert "review" in names
    assert "deploy" in names


def test_empty_directory(tmp_path):
    loader = SkillLoader(skill_dirs=[tmp_path / "nonexistent"])
    skills = loader.load_all()
    assert len(skills) == 0


def test_ignores_non_md_files(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "readme.txt").write_text("not a skill")
    (d / "commit.md").write_text("---\nname: commit\ndescription: test\n---\nBody.")
    loader = SkillLoader(skill_dirs=[d])
    skills = loader.load_all()
    assert len(skills) == 1


def test_source_from_dirname(skill_dirs):
    loader = SkillLoader(skill_dirs=skill_dirs)
    skills = loader.load_all()
    sources = {s.name: s.source for s in skills}
    assert sources["commit"] == "community"
    assert sources["deploy"] == "custom"
