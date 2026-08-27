"""#6054 engine half: a finding citing a line beyond EOF is stale by construction.

code_issues #8393 ('performance' at line 25847 of a 744-line file) sailed past
_finding_is_stale -- prose findings have no deterministic checker, so UNVERIFIED
fell toward building and the loop produced a destructive rewrite (PR #2861).
A cited line that does not exist is PROOF, not doubt: skip the build."""

import types

from archie_engine.engine import Engine


class _StubEngine:
    _finding_is_stale = Engine._finding_is_stale

    def __init__(self):
        self.config = types.SimpleNamespace(platform_workspace="/tmp/x")


def _patch_read(monkeypatch, content, error=None, truncated=False):
    import archie_engine.workspace_ops as wo
    monkeypatch.setattr(wo, "read_file", lambda root, path: (
        {"error": error} if error else {"content": content, "truncated": truncated}))


TASK_FAR = ("Fix this code issue in the A.R.C.H.I.E. platform.\n\n"
            "File: platform_v2/mcp_server/server.py (line 25847)\n"
            "Severity: high\nIssue: The server is loading tools from the database, "
            "which could be slow and resource-intensive.\n")
TASK_IN_RANGE = TASK_FAR.replace("(line 25847)", "(line 2)")
SHORT_FILE = "line one\nline two\nline three\n"


def test_beyond_eof_finding_is_stale(monkeypatch):
    _patch_read(monkeypatch, SHORT_FILE)
    assert _StubEngine()._finding_is_stale(TASK_FAR, "platform_v2/mcp_server/server.py") is True


def test_in_range_prose_finding_still_builds(monkeypatch):
    """An in-range prose finding has no deterministic checker -> UNVERIFIED -> build."""
    _patch_read(monkeypatch, SHORT_FILE)
    assert _StubEngine()._finding_is_stale(TASK_IN_RANGE, "platform_v2/mcp_server/server.py") is False


def test_truncated_read_never_stales_even_beyond_eof(monkeypatch):
    """A truncated read proves nothing about the real EOF -- fail toward building."""
    _patch_read(monkeypatch, SHORT_FILE, truncated=True)
    assert _StubEngine()._finding_is_stale(TASK_FAR, "x.py") is False


def test_unreadable_never_stales(monkeypatch):
    _patch_read(monkeypatch, "", error="boom")
    assert _StubEngine()._finding_is_stale(TASK_FAR, "x.py") is False


def test_no_line_marker_falls_through(monkeypatch):
    """Proposal-lane tasks carry no '(line N)' -- the check must not fire."""
    _patch_read(monkeypatch, SHORT_FILE)
    task = "Fix this code issue.\n\nFile: x.py\nIssue code: F401\nFinding: unused import\n"
    assert _StubEngine()._finding_is_stale(task, "x.py") is False
