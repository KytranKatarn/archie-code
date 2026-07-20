"""Fix-efficacy gate (#5003) — did the applied change actually resolve the finding?

WHY THIS EXISTS
Engine PR #2348 claimed to fix code_issues #7844 ("doc/routes.py line 56 exceeds 120
characters"). Its entire diff was one blank line added ~100 lines away. Line 56 was still
124 chars after the merge. The build reported ``{'success': True, 'stage': 'done'}`` and the
PR body said "Tests passed locally" — which was true and irrelevant: **a no-op diff passes
every test**. Nothing anywhere re-checked the finding itself, so "tests are green" was
silently substituted for "the bug is fixed".

This module re-asserts the ORIGINAL finding against the POST-EDIT file. It is deliberately
small and dependency-free: it runs inside the engine container, which has neither pyflakes
nor flake8 installed.

THREE OUTCOMES — the middle one is the point:
    RESOLVED       the finding provably no longer reproduces      -> proceed
    STILL_PRESENT  the finding provably still reproduces          -> FAIL CLOSED, open no PR
    UNVERIFIED     no deterministic checker for this finding type -> proceed, but say so

UNVERIFIED is not a failure and must NOT block: the queue is dominated by pyflakes codes
(F401/F841/F821/PYFLAKES) that this slice cannot check without adding a dependency, and
blocking them would halt the build loop entirely. It is reported so that "attempted" and
"verified effective" stop being the same number.
"""

import io
import re

RESOLVED = "resolved"
STILL_PRESENT = "still_present"
UNVERIFIED = "unverified"

# flake8-style code Repair Bay stores on a pyflakes finding ("F401 'os' imported but unused").
_PYFLAKES_CODE_RE = re.compile(r"\b(?:F\d{3}|PYFLAKES)\b", re.IGNORECASE)

# Findings sometimes arrive without a code — recognise pyflakes' own wording too.
_PYFLAKES_PHRASES = (
    "imported but unused",
    "assigned to but never used",
    "undefined name",
    "redefinition of unused",
    "f-string is missing placeholders",
    "unable to detect undefined names",
)

# "Line exceeds 120 characters (124)" / "line exceeds 120 chars"
_LINE_LEN_RE = re.compile(r"line\s+exceeds\s+(\d+)\s+char", re.IGNORECASE)
_ISSUE_RE = re.compile(r"^Issue:\s*(.+)$", re.MULTILINE)
_FILE_RE = re.compile(r"^File:\s*(\S+?)(?:\s*\(line\s*(\d+)\))?\s*$", re.MULTILINE)


def parse_issue(task: str) -> dict:
    """Pull {file, line, message} out of the task text built by ``_format_issue_task``."""
    out = {"file": None, "line": None, "message": ""}
    m = _FILE_RE.search(task or "")
    if m:
        out["file"] = m.group(1)
        if m.group(2):
            try:
                out["line"] = int(m.group(2))
            except ValueError:
                pass
    m = _ISSUE_RE.search(task or "")
    if m:
        out["message"] = m.group(1).strip()
    return out


def _check_line_length(message: str, file_text: str):
    """Exact re-assertion for a max-line-length finding.

    Returns (verdict, detail) or None when the message is not a line-length finding.

    The reported line NUMBER is deliberately ignored: an edit shifts line numbers, so the
    honest question is "does this file still violate the limit anywhere?". That biases toward
    FAIL CLOSED — an unrelated long line elsewhere holds the PR back, which is the safe
    direction for a gate whose whole purpose is to stop unverified fixes shipping.
    """
    m = _LINE_LEN_RE.search(message or "")
    if not m:
        return None
    try:
        limit = int(m.group(1))
    except ValueError:
        return None
    offenders = [(i, len(ln)) for i, ln in enumerate((file_text or "").splitlines(), 1) if len(ln) > limit]
    if not offenders:
        return RESOLVED, f"no line exceeds {limit} chars"
    shown = ", ".join(f"line {i} ({n} chars)" for i, n in offenders[:3])
    return STILL_PRESENT, f"still exceeds {limit} chars: {shown}"


def _pyflakes_findings(file_text: str):
    """(messages, ok) — pyflakes' own text for this source.

    ok is False when the source could not be analysed at all (pyflakes missing, or the file
    does not parse). A syntax error must NEVER read as "the finding is gone" — pyflakes emits
    nothing but the syntax error itself, which would otherwise look like a clean file.
    """
    try:
        from pyflakes.api import check as pyflakes_check
        from pyflakes.reporter import Reporter
    except ImportError:
        return [], False

    out, err = io.StringIO(), io.StringIO()
    try:
        pyflakes_check(file_text or "", "target", Reporter(out, err))
    except Exception:
        return [], False
    if err.getvalue().strip():  # syntax error / unparseable
        return [], False
    return out.getvalue().splitlines(), True


def _needle_from_message(message: str) -> str:
    """Strip the flake8 code prefix, leaving pyflakes' own wording.

    Repair Bay stores "F401 'os' imported but unused"; pyflakes itself emits
    "target:1:1 'os' imported but unused" — no code. Matching on the descriptive tail is
    what makes the two comparable.
    """
    text = (message or "").strip()
    text = _PYFLAKES_CODE_RE.sub("", text, count=1).strip()
    return text.strip(" -:")


def _check_pyflakes(message: str, file_text: str):
    """Re-assert a pyflakes finding (F401/F841/F821/...) by re-running pyflakes.

    Returns (verdict, detail) or None when the message is not a pyflakes finding.

    Every uncertainty returns UNVERIFIED rather than a verdict: pyflakes absent, source
    unparseable, or a message with no comparable wording left after stripping the code.
    """
    msg = message or ""
    if not _PYFLAKES_CODE_RE.search(msg) and not any(p in msg.lower() for p in _PYFLAKES_PHRASES):
        return None

    needle = _needle_from_message(msg)
    if len(needle) < 8:  # nothing distinctive left to compare
        return UNVERIFIED, f"no comparable pyflakes wording in: {msg[:60]}"

    findings, ok = _pyflakes_findings(file_text)
    if not ok:
        return UNVERIFIED, "pyflakes unavailable or source does not parse"

    still = [ln for ln in findings if needle in ln]
    if still:
        return STILL_PRESENT, f"pyflakes still reports: {still[0][:100]}"
    return RESOLVED, f"pyflakes no longer reports: {needle[:80]}"


# Ordered; the first checker that recognises the message wins.
_CHECKERS = (_check_line_length, _check_pyflakes)


def check(task: str, file_text: str):
    """Re-assert the finding described by ``task`` against ``file_text`` (POST-edit content).

    ``file_text`` MUST be the raw file, not a line-numbered rendering — the engine's
    ``file_ops`` read defaults to ``numbered=True``, which would inflate every measured
    length and make every check report STILL_PRESENT.

    Returns ``(verdict, detail)``.
    """
    message = parse_issue(task).get("message") or ""
    if not message:
        return UNVERIFIED, "no parseable Issue: line in the task"
    for checker in _CHECKERS:
        got = checker(message, file_text)
        if got is not None:
            return got
    return UNVERIFIED, f"no deterministic checker for: {message[:80]}"
