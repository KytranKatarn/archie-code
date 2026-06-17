"""Tests for GitOpsTool repo lifecycle (#4254) + branch+PR-only safety rails
(ADR-003 / #4255) + the router git-op kwarg fix (#4253)."""

import subprocess

import pytest

from archie_engine.tools.git_ops import GitOpsTool, PROTECTED_BRANCHES
from archie_engine.router import CommandRouter
from archie_engine.tools import ToolRegistry
from archie_engine.tools.base import BaseTool, ToolResult


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo on branch 'main' with one initial commit."""
    def g(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True,
                       capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)],
                   check=True, capture_output=True, text=True)
    g("config", "user.email", "engine@test")
    g("config", "user.name", "engine")
    g("config", "commit.gpgsign", "false")
    (tmp_path / "archie_engine").mkdir()
    (tmp_path / "archie_engine" / "x.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("# repo\n")
    g("add", "README.md")
    g("commit", "-q", "-m", "init")
    return tmp_path


def _tool(repo):
    return GitOpsTool(workspace=repo)


# --- read-only ---

async def test_status_reports_untracked(repo):
    r = await _tool(repo).execute(operation="status")
    assert r.success
    # git --short collapses a fully-untracked dir to "?? archie_engine/"
    assert "archie_engine" in r.output


# --- add: deny-by-default scope guarded ---

async def test_add_in_scope_path_stages(repo):
    t = _tool(repo)
    r = await t.execute(operation="add", paths=["archie_engine/x.py"])
    assert r.success, r.error
    staged = await t.execute(operation="diff", staged=True)
    assert "x.py" in staged.output


async def test_add_out_of_scope_path_denied(repo):
    (repo / ".env").write_text("SECRET=1\n")
    r = await _tool(repo).execute(operation="add", paths=[".env"])
    assert not r.success
    assert "scope guard" in r.error.lower()


async def test_add_refuses_to_stage_everything(repo):
    r = await _tool(repo).execute(operation="add", paths=None)
    assert not r.success
    assert "refusing to stage everything" in r.error.lower()


# --- commit ---

async def test_commit_requires_message(repo):
    r = await _tool(repo).execute(operation="commit")
    assert not r.success
    assert "message" in r.error.lower()


async def test_add_commit_roundtrip(repo):
    t = _tool(repo)
    await t.execute(operation="add", paths=["archie_engine/x.py"])
    r = await t.execute(operation="commit", message="add x")
    assert r.success, r.error
    log = await t.execute(operation="log", count=1)
    assert "add x" in log.output


# --- branch ---

async def test_branch_create_and_list(repo):
    t = _tool(repo)
    assert (await t.execute(operation="branch", action="create", name="feat/y")).success
    lst = await t.execute(operation="branch")
    assert "feat/y" in lst.output


# --- push: branch+PR-only tool-level gate (#4255) ---

async def test_push_refuses_protected_branch(repo):
    # repo is on 'main' — the engine must never push to it
    r = await _tool(repo).execute(operation="push")
    assert not r.success
    assert "refusing to push protected branch" in r.error.lower()
    assert "main" in PROTECTED_BRANCHES


async def test_push_allows_feature_branch_attempt(repo):
    t = _tool(repo)
    await t.execute(operation="branch", action="create", name="feat/z")
    r = await t.execute(operation="push")
    # no 'origin' remote in a throwaway repo → push fails, but NOT due to protection
    assert not r.success
    assert "refusing to push protected branch" not in r.error.lower()


# --- clone allowlist ---

async def test_clone_denies_unlisted_repo(repo):
    r = await _tool(repo).execute(operation="clone", url="https://github.com/evil/repo.git")
    assert not r.success
    assert "allowlist" in r.error.lower()


async def test_clone_requires_url(repo):
    r = await _tool(repo).execute(operation="clone", url=None)
    assert not r.success


async def test_clone_denies_lookalike_repo(repo):
    # exact host/owner/repo match — a look-alike must NOT slip through a substring check
    r = await _tool(repo).execute(operation="clone",
                                  url="https://github.com/KytranKatarn/archie-code-evil.git")
    assert not r.success
    assert "allowlist" in r.error.lower()


def test_repo_identity_normalizes_and_rejects_lookalikes():
    from archie_engine.tools.git_ops import _repo_identity, ALLOWED_CLONE_REPOS
    for u in ("https://github.com/KytranKatarn/archie-code.git",
              "git@github.com:KytranKatarn/archie-code.git",
              "https://github.com/kytrankatarn/archie-code"):
        assert _repo_identity(u) in ALLOWED_CLONE_REPOS, u
    assert _repo_identity("https://github.com/KytranKatarn/archie-code-evil") not in ALLOWED_CLONE_REPOS
    assert _repo_identity("not-a-url") is None


# --- router #4253: git ops dispatched with operation= (not subcommand=), no working_dir ---

class _RecordingGitTool(BaseTool):
    name = "git_ops"

    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(success=True, output="ok")


class _FakeInference:
    async def chat(self, **kwargs):
        return {"message": {"content": ""}, "model": "t"}


class _FakePersonality:
    def build_system_prompt(self):
        return ""


async def test_router_git_op_uses_operation_kwarg_no_working_dir():
    reg = ToolRegistry()
    tool = _RecordingGitTool()
    reg.register(tool)
    router = CommandRouter(tools=reg, inference=_FakeInference(),
                           personality_builder=_FakePersonality())
    intent = {"type": "git_operation", "raw_input": "git status", "entities": {}}
    await router.route(intent, {})
    assert len(tool.calls) == 1
    assert tool.calls[0].get("operation") == "status"
    assert "subcommand" not in tool.calls[0]
    assert "working_dir" not in tool.calls[0]
