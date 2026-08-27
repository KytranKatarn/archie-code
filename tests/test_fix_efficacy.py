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
    """A finding NO checker recognises must pass through — blocking it would halt the loop.

    UPDATED 2026-07-20: this used F401 as its example of "uncheckable". Since pyflakes became
    a runtime dependency, F401 IS checkable (see the pyflakes tests below), so the example
    moved to a genuinely unrecognised detector. The GUARANTEE pinned here is unchanged and is
    the point: no checker -> UNVERIFIED -> never fails closed.
    """
    task = _format_issue_task(
        {"message": "CYCLOMATIC_COMPLEXITY function too complex (18)", "severity": "low"}, "a/b.py"
    )
    verdict, detail = fix_efficacy.check(task, "def f():\n    return 1\n")
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


# --- pyflakes-backed checkers (#5003 slice 2) ----------------------------------------------
# 1327 of 2230 open findings were UNVERIFIED because the only checker was line-length, and
# the queue is dominated by F401/F841/F821. pyflakes is now a runtime dependency so those
# findings can be re-asserted for real.

import pytest

pyflakes = pytest.importorskip("pyflakes", reason="pyflakes is a runtime dep of the engine image")


def _t(message):
    return _format_issue_task({"message": message, "severity": "low"}, "a.py")


@pytest.mark.parametrize(
    "message,broken_src,fixed_src",
    [
        ("F401 'os' imported but unused", "import os\n", "x = 1\n"),
        (
            "F841 local variable 'y' is assigned to but never used",
            "def f():\n    y = 1\n",
            "def f():\n    return 1\n",
        ),
        ("F821 undefined name 'zzz'", "print(zzz)\n", "zzz = 1\nprint(zzz)\n"),
    ],
)
def test_pyflakes_finding_round_trip(message, broken_src, fixed_src):
    """Each code must report still_present on the unfixed source and resolved on the fixed one."""
    assert fix_efficacy.check(_t(message), broken_src)[0] == fix_efficacy.STILL_PRESENT
    assert fix_efficacy.check(_t(message), fixed_src)[0] == fix_efficacy.RESOLVED


def test_syntax_error_is_unverified_never_resolved():
    """A file that does not parse makes pyflakes emit ONLY a syntax error. That must not read
    as 'the finding is gone' — it would let a broken edit through the gate as a clean fix."""
    v, detail = fix_efficacy.check(_t("F401 'os' imported but unused"), "def broken(\n")
    assert v == fix_efficacy.UNVERIFIED
    assert "parse" in detail or "unavailable" in detail


def test_bare_pyflakes_wording_without_a_code_is_recognised():
    """Some findings arrive with no F-code, just pyflakes' own text."""
    assert fix_efficacy.check(_t("'os' imported but unused"), "import os\n")[0] == fix_efficacy.STILL_PRESENT


def test_ruff_backtick_quoting_matches_pyflakes_output():
    """ruff stores "F401 `os` imported but unused"; pyflakes emits 'os'. Before #6086 the
    quoting mismatch made every ruff-sourced finding read RESOLVED while still present —
    the same defect that drove the platform reconciler's archive/recreate oscillator
    (platform PR #2896). The needle must unify quoting before comparing."""
    task = _t("F401 `os` imported but unused")
    assert fix_efficacy.check(task, "import os\n")[0] == fix_efficacy.STILL_PRESENT
    assert fix_efficacy.check(task, "x = 1\n")[0] == fix_efficacy.RESOLVED


def test_unrelated_pyflakes_finding_does_not_mask_a_fix():
    """Only the ORIGINAL finding matters. An unrelated warning elsewhere must not make a
    genuinely-fixed finding look unresolved."""
    src = "import sys\n\n\ndef f():\n    return 1\n"  # F401 on sys, but the 'os' finding is gone
    assert fix_efficacy.check(_t("F401 'os' imported but unused"), src)[0] == fix_efficacy.RESOLVED


def test_line_length_checker_still_wins_for_its_own_findings():
    """Checker ordering: a line-length message must not fall through to pyflakes."""
    assert fix_efficacy.check(TASK_7844, "x" * 124)[0] == fix_efficacy.STILL_PRESENT
    assert fix_efficacy.check(TASK_7844, "x" * 80)[0] == fix_efficacy.RESOLVED


# --- #6086: the beyond-EOF shortcut must not pre-empt a recognised checker -----------------
# test_not_stale_when_finding_still_present above IS the regression case: TASK_7844 cites
# line 56, the file has ONE 124-char line, and before #6086 the #6054 EOF shortcut fired
# first and judged a still-reproducing finding stale. These pin the scoping that fixes it.


def test_recognizes_claims_checker_classes_only():
    assert fix_efficacy.recognizes("Line exceeds 120 characters (124)") is True
    assert fix_efficacy.recognizes("F401 'os' imported but unused") is True
    assert fix_efficacy.recognizes("F401 `os` imported but unused") is True
    assert fix_efficacy.recognizes("The server is loading tools from the database") is False
    assert fix_efficacy.recognizes("") is False


def test_recognised_but_unverifiable_beyond_eof_is_NOT_stale(tmp_path):
    """A pyflakes-class finding on a file that does not parse is DOUBT, not proof — even
    when the cited line lies beyond EOF. Doubt fails toward building; the #6054 beyond-EOF
    rule is scoped to messages NO checker recognises, mirroring the platform reconciler."""
    (tmp_path / "f.py").write_text("def broken(\n")
    task = _format_issue_task(
        {"message": "F401 'os' imported but unused", "severity": "low", "line_number": 99}, "f.py"
    )
    assert Engine._finding_is_stale(_selfish(tmp_path), task, "f.py") is False
