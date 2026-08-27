"""#5933: gate which findings an autonomous local coder may attempt at all.

FAIL CLOSED. Only the classes proven mechanical (find/replace-shaped) are
buildable; everything else — semantic, architectural and above all SECURITY
findings — is refused. A refused finding still exists as a proposal for a
human; it just never dispatches to an autonomous coder.

Why this gate is load-bearing (measured):
- 2026-08-27: 5/5 open issues-lane PRs were defective — three boot/import
  breaking — and every one originated from a heuristic "hardcoded secret"
  finding. A plausible-looking secret-handling "fix" is the most dangerous
  thing a small local model writes (#2869, #2891: both stripped the
  Docker-secrets helper for bare os.getenv).
- Static-tier re-verify measured 0 fixed / 327 deployed (0%) on 2026-08-22.
- KB #282665: SQL/DIRECT_OLLAMA fix-gen was 100% garbage.

MECHANICAL_ISSUE_CODES mirrors the platform's _AUTO_FIX_PRIORITY_ISSUE_CODES
(platform_v2/services/audit_pipeline.py) — the classes its own drain trusts
for auto fix-gen. The platform cannot be imported from this repo, so the set
is restated: KEEP THE TWO IN STEP.

Two faces of one definition, because the two lanes carry different data:
- audit PROPOSALS carry a real metadata issue_code  -> is_mechanical_code()
- code_issues rows carry PROSE, not codes           -> is_mechanical_message()
"""

MECHANICAL_ISSUE_CODES = frozenset(
    {
        "F401",
        "F841",
        "F541",
        "PYFLAKES",
        "WRONG_SUBMODULE_IMPORT",
        "WRONG_ROOT_IMPORT",
        "MISSING_SYMBOL",
        "F821",
        "BARE_EXCEPT",
    }
)

# The pyflakes-class wording the mechanical classes surface as when a scanner
# writes prose instead of a code. Anything that matches NONE of these is not
# mechanical — that is the fail-closed default, and it is what refuses every
# "hardcoded secret" / "insecure X" / "refactor for clarity" finding without
# needing to enumerate the ways a heuristic detector can phrase itself.
_MECHANICAL_MESSAGE_PATTERNS = (
    "imported but unused",
    "assigned to but never used",
    "redefinition of unused",
    "f-string is missing placeholders",
    "undefined name",
    "bare except",
)


def is_mechanical_code(issue_code) -> bool:
    """True only for an allowlisted mechanical issue code. Unknown/empty -> False."""
    return (issue_code or "").strip().upper() in MECHANICAL_ISSUE_CODES


def is_mechanical_message(message) -> bool:
    """True only when the finding's prose matches a mechanical pattern. Unknown -> False."""
    low = (message or "").lower()
    return any(p in low for p in _MECHANICAL_MESSAGE_PATTERNS)
