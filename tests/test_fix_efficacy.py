"""Tests for the fix-efficacy gate (#5003).

Engine PR #2348 claimed to fix code_issues #7844 ("doc/routes.py line 56 exceeds 120
characters"). Its entire diff was one blank line added ~100 lines away; line 56 was still
124 chars after it merged. The build returned success and the PR said "Tests passed
locally" — true, and irrelevant: a no-op diff passes every test.

These tests pin the distinction the gate exists to make: green tests answer "did I break
anything", never "did I fix the thing".
"""

from archie_engine import fix_efficacy
from archie_engine.engine import _format_issue_task

# The exact shape _format_issue_task emits — parsing this is the gate's only input contract.
TASK_7844 = _format_issue_task(
    {
        "message": "Line exceeds 120 characters (124)",
        "suggestion": "Break into multiple lines",
        "severity": "low",
        "line_number": 56,
    },
    "platform_v2/tools/doc/routes.py",
)

LONG = "x" * 124
SHORT = "y" * 40


def test_parses_the_real_task_format():
    got = fix_efficacy.parse_issue(TASK_7844)
    assert got["file"] == "platform_v2/tools/doc/routes.py"
    assert got["line"] == 56
    assert got["message"] == "Line exceeds 120 characters (124)"


# --- the #2348 failure: an edit that does not touch the reported problem ------------------


def test_2348_repro_unfixed_file_is_still_present():
    """The blank-line 'fix': file changed, finding untouched -> must FAIL CLOSED."""
    after_2348 = "\n".join([SHORT, LONG, SHORT, ""])  # a blank line added; long line survives
    verdict, detail = fix_efficacy.check(TASK_7844, after_2348)
    assert verdict == fix_efficacy.STILL_PRESENT
    assert "124 chars" in detail


def test_7844_real_fix_is_resolved():
    """The actual fix (wrap the line) -> no line exceeds the limit -> RESOLVED."""
    after_real_fix = "\n".join([SHORT, "z" * 97, SHORT])
    verdict, _ = fix_efficacy.check(TASK_7844, after_real_fix)
    assert verdict == fix_efficacy.RESOLVED


def test_boundary_at_the_limit_is_not_a_violation():
    """Exactly at the limit passes; one over does not."""
    assert fix_efficacy.check(TASK_7844, "a" * 120)[0] == fix_efficacy.RESOLVED
    assert fix_efficacy.check(TASK_7844, "a" * 121)[0] == fix_efficacy.STILL_PRESENT


# --- UNVERIFIED must never block ----------------------------------------------------------


def test_unknown_finding_type_is_unverified_not_blocked():
    """The queue is dominated by pyflakes codes this slice cannot check (no pyflakes in the
    engine container). Those MUST pass through — blocking them would halt the build loop."""
    task = _format_issue_task({"message": "F401 'os' imported but unused", "severity": "low"}, "a/b.py")
    verdict, detail = fix_efficacy.check(task, "import os\n")
    assert verdict == fix_efficacy.UNVERIFIED
    assert verdict != fix_efficacy.STILL_PRESENT, "an uncheckable finding must not fail closed"


def test_unparseable_task_is_unverified():
    verdict, _ = fix_efficacy.check("no issue line here at all", "whatever")
    assert verdict == fix_efficacy.UNVERIFIED


# --- the numbered-read hazard -------------------------------------------------------------


def test_line_numbered_input_would_break_the_check():
    """Documents WHY the caller must pass numbered=False.

    file_ops read defaults to numbered=True; those prefixes inflate every measured length.
    A file that is genuinely fixed would be reported as still broken, blocking every build.
    This test locks in the failure mode so the numbered=False call site is never 'tidied'.
    """
    # 118 chars: genuinely under the 120 limit, but close enough that a line-number prefix
    # pushes it over — which is exactly how the false failure would occur in practice.
    fixed_raw = "\n".join(["a" * 118, "b" * 118])
    assert fix_efficacy.check(TASK_7844, fixed_raw)[0] == fix_efficacy.RESOLVED

    numbered = "\n".join(f"{i:>6}\t{'a' * 118}" for i in range(1, 3))  # simulated numbered render
    assert len(numbered.splitlines()[0]) == 125, "prefix must push the line over the limit"

    # SAME underlying file, measured with prefixes -> a FALSE miss that would block the build.
    assert fix_efficacy.check(TASK_7844, numbered)[0] == fix_efficacy.STILL_PRESENT


# --- Engine._finding_is_stale: the guards that must fail TOWARD building (#5004) -----------
# A false "stale" silently skips real work — strictly worse than spending one build cycle.
# These call the real helper unbound with a minimal self, so the guards are exercised for real.

import types

from archie_engine.engine import Engine


def _selfish(tmp_path):
    return types.SimpleNamespace(config=types.SimpleNamespace(platform_workspace=str(tmp_path)))


def test_stale_when_finding_provably_gone(tmp_path):
    (tmp_path / "f.py").write_text("short line\n")
    assert Engine._finding_is_stale(_selfish(tmp_path), TASK_7844, "f.py") is True


def test_not_stale_when_finding_still_present(tmp_path):
    (tmp_path / "f.py").write_text("x" * 124 + "\n")
    assert Engine._finding_is_stale(_selfish(tmp_path), TASK_7844, "f.py") is False


def test_missing_file_is_NOT_stale(tmp_path):
    """Unreadable path -> we know nothing -> build. Never skip on ignorance."""
    assert Engine._finding_is_stale(_selfish(tmp_path), TASK_7844, "does_not_exist.py") is False


def test_unknown_finding_type_is_NOT_stale(tmp_path):
    """No deterministic checker (pyflakes codes) -> UNVERIFIED -> must still build."""
    (tmp_path / "f.py").write_text("import os\n")
    task = _format_issue_task({"message": "F401 'os' imported but unused", "severity": "low"}, "f.py")
    assert Engine._finding_is_stale(_selfish(tmp_path), task, "f.py") is False
