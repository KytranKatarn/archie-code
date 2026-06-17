"""Tests for the engine's deny-by-default scope guard (ADR-003) and its wiring
into CommandRouter file mutations."""

import pytest

from archie_engine.scope_guard import (
    is_in_scope,
    check_diff_paths,
    DEFAULT_ARCHIE_CODE_SCOPE,
)
from archie_engine.router import CommandRouter
from archie_engine.tools import ToolRegistry
from archie_engine.tools.base import BaseTool, ToolResult


# ---------------------------------------------------------------------------
# scope_guard unit tests (synchronous, default archie-code config)
# ---------------------------------------------------------------------------

def test_allows_engine_source_tests_docs():
    assert is_in_scope("archie_engine/router.py")
    assert is_in_scope("archie_engine/tools/file_ops.py")
    assert is_in_scope("tests/test_scope_guard.py")
    assert is_in_scope("docs/design.md")


def test_blocks_env_and_secrets_even_nested():
    assert not is_in_scope(".env")
    assert not is_in_scope("archie_engine/.env")
    assert not is_in_scope("archie_engine/local.env")
    assert not is_in_scope("secrets/key.txt")
    assert not is_in_scope("id_ed25519")
    assert not is_in_scope("docs/server.pem")


def test_blocks_infra_ci_and_git_internals():
    assert not is_in_scope("docker-compose.yml")
    assert not is_in_scope("docker-compose.override.yml")
    assert not is_in_scope("Dockerfile")
    assert not is_in_scope(".github/workflows/ci.yml")
    assert not is_in_scope("install.sh")
    assert not is_in_scope(".git/config")
    assert not is_in_scope("Modelfile.archie-coder")


def test_engine_cannot_weaken_its_own_guard():
    # blocked even though it lives under the allowed archie_engine/ prefix
    assert not is_in_scope("archie_engine/scope_guard.py")


def test_blocks_traversal_and_absolute():
    assert not is_in_scope("../platform_v2/app.py")
    assert not is_in_scope("/etc/passwd")
    assert not is_in_scope("archie_engine/../.env")
    assert not is_in_scope("")
    assert not is_in_scope(None)  # type: ignore[arg-type]


def test_denies_paths_outside_allowed_dirs():
    # real files in the repo that are NOT under an allowed prefix → denied
    assert not is_in_scope("README.md")
    assert not is_in_scope("pyproject.toml")
    assert not is_in_scope("archie-tui/main.go")


def test_check_diff_paths_returns_only_violations():
    paths = ["archie_engine/x.py", ".env", "tests/y.py", "docker-compose.yml"]
    assert sorted(check_diff_paths(paths)) == [".env", "docker-compose.yml"]


def test_malformed_allowed_config_fails_closed():
    # an over-broad allowed prefix must NOT turn into allow-all
    bad_cfg = {"allowed_paths": [".", "/", "../"], "blocked_globs": []}
    assert not is_in_scope("archie_engine/router.py", bad_cfg)
    assert not is_in_scope("anything/at/all.py", bad_cfg)


# ---------------------------------------------------------------------------
# CommandRouter integration — file mutations are gated, reads are not
# ---------------------------------------------------------------------------

class _RecordingFileTool(BaseTool):
    name = "file_ops"

    def __init__(self):
        self.calls = []

    async def execute(self, **kwargs) -> ToolResult:
        self.calls.append(kwargs)
        return ToolResult(success=True, output="ok")


class _FakeInference:
    async def chat(self, **kwargs):
        return {"message": {"content": "x"}, "model": "test"}


class _FakePersonality:
    def build_system_prompt(self) -> str:
        return ""


def _router():
    reg = ToolRegistry()
    tool = _RecordingFileTool()
    reg.register(tool)
    router = CommandRouter(
        tools=reg,
        inference=_FakeInference(),
        personality_builder=_FakePersonality(),
    )
    return router, tool


async def test_router_denies_write_to_env_without_invoking_tool():
    router, tool = _router()
    intent = {"type": "file_operation", "raw_input": "write secrets to .env",
              "entities": {"files": [".env"]}}
    resp = await router.route(intent, {})
    assert resp["success"] is False
    assert "scope guard" in resp["response"].lower()
    assert tool.calls == []  # the tool must NEVER be reached for a denied write


async def test_router_allows_write_in_scope_and_drops_working_dir_kwarg():
    router, tool = _router()
    intent = {"type": "file_operation", "raw_input": "write file",
              "entities": {"files": ["archie_engine/new_feature.py"]}}
    resp = await router.route(intent, {})
    assert resp["success"] is True
    assert len(tool.calls) == 1
    # #4253: the dead working_dir kwarg is no longer forwarded to the tool
    assert "working_dir" not in tool.calls[0]
    assert tool.calls[0]["operation"] == "write"


async def test_router_allows_read_anywhere_in_workspace():
    # reads are not scope-gated at the router (tool's workspace check covers them)
    router, tool = _router()
    intent = {"type": "file_operation", "raw_input": "read pyproject.toml",
              "entities": {"files": ["pyproject.toml"]}}
    resp = await router.route(intent, {})
    assert resp["success"] is True
    assert tool.calls[0]["operation"] == "read"
