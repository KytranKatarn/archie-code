"""#6657 — the ws `run …` shell path is an ALLOWLIST, not a denylist.

The pre-fix denylist had six substrings; ``cat /workspace-platform/.env`` matched
none of them. The untrusted path now: no metacharacters, exec without a shell,
four programs, paths confined to the workspaces, credentials scrubbed from env.
The trusted path (build loop) is unchanged and is asserted separately.
"""

import os
from pathlib import Path

import pytest

from archie_engine.router import CommandRouter
from archie_engine.tools import ToolRegistry
from archie_engine.tools.shell_ops import ShellOpsTool, ShellPolicyError, scrubbed_env, validate_untrusted


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIE_ENGINE_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ARCHIE_PLATFORM_WORKSPACE", raising=False)
    monkeypatch.delenv("ARCHIE_ENGINE_WS_ROOTS", raising=False)
    return tmp_path


REFUSED = [
    "cat /etc/passwd",
    "cat /workspace-platform/.env",
    "ls /etc",
    "pytest; rm -rf /",
    "pytest && cat .env",
    "git log | head",
    "git -c core.pager=cat log",
    "git log --output=/tmp/x",
    "git push origin main",
    "git diff --ext-diff",
    "python -c print(1)",
    "python3 script.py",
    "/usr/bin/env",
    "ls $(whoami)",
    "ls `whoami`",
    "ls > out.txt",
    "curl http://x",
    "rm -rf .",
    "",
]
ALLOWED = [
    "pytest -q tests/",
    "pytest -x -k policy",
    "python -m pytest -q",
    "python3 -m py_compile a.py",
    "git status",
    "git status --short",
    "git diff --stat",
    "git log --oneline -n5",
    "git log -3",
    "git rev-parse --abbrev-ref HEAD",
    "git ls-files",
    "ls -la",
    "ls src",
]


@pytest.mark.parametrize("cmd", REFUSED)
def test_refused(ws, cmd):
    with pytest.raises(ShellPolicyError):
        validate_untrusted(cmd, [ws])


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(ws, cmd):
    assert validate_untrusted(cmd, [ws])[0] in ("pytest", "python", "python3", "git", "ls")


def test_absolute_paths_must_stay_inside_a_root(ws, tmp_path_factory):
    assert validate_untrusted(f"ls {ws}", [ws])
    other = tmp_path_factory.mktemp("other")
    with pytest.raises(ShellPolicyError):
        validate_untrusted(f"ls {other}", [ws])
    with pytest.raises(ShellPolicyError):
        validate_untrusted("ls ../..", [ws])


def test_scrubbed_env_drops_credentials(monkeypatch):
    monkeypatch.setenv("ENGINE_WS_TOKEN", "t")
    monkeypatch.setenv("ARCHIE_HUB_API_KEY", "k")
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("GITHUB_TOKEN", "g")
    monkeypatch.setenv("SAFE_SETTING", "1")
    env = scrubbed_env()
    for k in ("ENGINE_WS_TOKEN", "ARCHIE_HUB_API_KEY", "INTERNAL_API_KEY", "DB_PASSWORD", "GITHUB_TOKEN"):
        assert k not in env
    assert env["SAFE_SETTING"] == "1" and "PATH" in env


@pytest.mark.asyncio
async def test_untrusted_execute_refuses_and_runs_without_a_shell(ws, monkeypatch):
    tool = ShellOpsTool(workspace=ws)
    r = await tool.execute(command="cat /etc/passwd")
    assert r.success is False and r.error.startswith("refused by shell policy")
    (ws / "x.txt").write_text("hi\n")
    monkeypatch.setenv("ENGINE_WS_TOKEN", "leak-me")
    r = await tool.execute(command="ls")
    assert r.success is True and "x.txt" in r.output
    # exec, not shell: a metachar never reaches a shell because it never passes validate_untrusted
    r = await tool.execute(command="ls; echo pwned")
    assert r.success is False and "pwned" not in r.output


@pytest.mark.asyncio
async def test_trusted_execute_keeps_pipes_for_the_build_loop(ws):
    tool = ShellOpsTool(workspace=ws)
    (ws / "a").write_text("1\n2\n3\n")
    r = await tool.execute(command="cat a | wc -l", trusted=True)
    assert r.success is True and r.output.strip() == "3"


@pytest.mark.asyncio
async def test_router_run_command_goes_through_the_untrusted_path(ws):
    registry = ToolRegistry()
    registry.register(ShellOpsTool(workspace=ws))
    router = CommandRouter(registry, None)  # (tools, inference) — no model needed for the shell path
    out = await router._handle_shell_command("run cat /etc/passwd", {}, {})
    assert out["success"] is False and "refused by shell policy" in out["response"]
