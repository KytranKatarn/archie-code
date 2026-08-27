"""Diff-safety gate (#6053): refuse a destructive build output BEFORE test/push.

Engine PR #2861 deleted 698 of mcp_server/server.py's 744 lines and replaced
them with placeholder credentials ('your_dbname', 'your_password') -- and
PASSED the test gate, because the platform test command never imports that
module. Green tests answer "did I break what the suite covers", never "is this
change sane"; for a destructive rewrite the DIFF is the only tell. Same lesson
shape as the fix-efficacy gate (#5003) one step earlier in the loop.

Pure text math over `git diff` output -- no git, no I/O -- so every rule is
trivially testable. BuildLoop supplies the diff and per-file base line counts.

Rules (in order):
1. PLACEHOLDER  -- an added line carrying template credentials/values
   ('your_dbname', 'changeme', '<your api key>') is an automatic refusal.
   NEVER carved out: no legitimate engine fix introduces placeholder secrets.
2. DELETION RATIO -- a pre-existing file losing > DELETION_RATIO_MAX of its
   base lines AND at least DELETION_FLOOR_LINES lines is refused, unless the
   task text explicitly asks for a removal. The floor keeps small-file edits
   (3 of 5 lines) out of scope; new files (base 0) cannot trip it.
"""

from __future__ import annotations

import re

DELETION_RATIO_MAX = 0.40
DELETION_FLOOR_LINES = 20

# Quoted template values only -- matching bare prose would flag comments that
# merely MENTION placeholders. 'your_<word>', 'changeme', '<your ...>'.
_PLACEHOLDER_RE = re.compile(
    r"""(?ix) ["'] (?: your_[a-z0-9_]+ | changeme | <your[^"']* ) ["'] """
)

# Narrow on purpose: the engine's fix tasks say "Make the MINIMAL, correct
# change" -- only a task that NAMES a removal relaxes the ratio rule.
_REMOVAL_ASK_RE = re.compile(
    r"(?i)\b(remove|delete|strip|drop|retire)\b.{0,60}"
    r"\b(file|module|class|function|method|block|section|import|lines?|code)\b"
)


def task_asks_removal(task: str) -> bool:
    return bool(_REMOVAL_ASK_RE.search(task or ""))


def parse_diff(diff_text: str) -> dict:
    """Unified diff -> {path: {"added": [line, ...], "deleted": int}}.

    Path is taken from the '+++ b/...' header (falling back to '--- a/...' for
    a deleted file). Binary chunks contribute no counted lines.
    """
    files: dict = {}
    cur = None
    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git"):
            cur = None
            continue
        if line.startswith("+++ "):
            name = line[4:].strip()
            if name != "/dev/null":
                cur = name[2:] if name.startswith("b/") else name
                files.setdefault(cur, {"added": [], "deleted": 0})
            continue
        if line.startswith("--- "):
            name = line[4:].strip()
            if name != "/dev/null" and cur is None:
                cand = name[2:] if name.startswith("a/") else name
                cur = cand
                files.setdefault(cur, {"added": [], "deleted": 0})
            continue
        if cur is None:
            continue
        if line.startswith("+"):
            files[cur]["added"].append(line[1:])
        elif line.startswith("-"):
            files[cur]["deleted"] += 1
    return files


def check(diff_text: str, base_lines: dict, task: str = "") -> tuple[bool, str]:
    """(ok, reason). base_lines maps path -> line count at HEAD (0/absent = new file)."""
    files = parse_diff(diff_text)

    for path, info in files.items():
        for added in info["added"]:
            if _PLACEHOLDER_RE.search(added):
                return False, (
                    f"placeholder value in added line of {path}: {added.strip()[:80]!r} "
                    "-- template credentials/values are never a real fix"
                )

    removal_ok = task_asks_removal(task)
    for path, info in files.items():
        base = int(base_lines.get(path) or 0)
        deleted = info["deleted"]
        if base <= 0 or deleted < DELETION_FLOOR_LINES:
            continue
        ratio = deleted / base
        if ratio > DELETION_RATIO_MAX and not removal_ok:
            return False, (
                f"deletion ratio {ratio:.0%} on {path} ({deleted} of {base} lines) exceeds "
                f"{DELETION_RATIO_MAX:.0%} and the task does not ask for a removal "
                "-- refusing a destructive rewrite (#6053, engine PR #2861)"
            )

    return True, ""
