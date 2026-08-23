"""Deny-by-default path scope guard for the A.R.C.H.I.E. engine.

The engine runs an autonomous build loop scoped (ADR-003, 2026-06-17) to its OWN
repo (``archie-code``) ONLY. This guard is the PRIMARY safety gate for every file
mutation the engine performs: a path is writable ONLY IF, after normalization, it
does not escape the repo via ``..``/absolute traversal, does not match any
``blocked_globs``, AND sits under an ``allowed_paths`` prefix on a real directory
boundary. Blocked always wins. It MUST fail closed — deny on anything unsafe or
malformed, never fail open.

Ported from the Codex CLI scope guard
(``platform_v2/services/agents/codex_scope.py``); identical normalization
semantics, engine-local default config.
"""

from __future__ import annotations

import fnmatch
import posixpath
from typing import Iterable, Optional

# Deny-by-default scope for the archie-code repo (ADR-003). The engine may create
# and edit its own source, tests and docs; it must NEVER touch secrets, infra, CI,
# git internals, or its OWN scope guard — even though they live inside the same
# repo. Blocked globs always win over allowed paths.
DEFAULT_ARCHIE_CODE_SCOPE: dict = {
    "allowed_paths": [
        "archie_engine/",
        "tests/",
        "docs/",
    ],
    "blocked_globs": [
        "*.env",
        ".env*",
        "*.key",
        "*.pem",
        "*.pfx",
        "id_rsa*",
        "id_ed25519*",
        "secrets/*",
        "docker-compose*",
        "Dockerfile*",
        "Modelfile*",
        "install.sh",
        ".git/*",
        ".github/*",
        # the engine must not be able to weaken its own safety gate
        "archie_engine/scope_guard.py",
    ],
}


# Deny-by-default scope for the archie-PLATFORM repo (project #380 — engine→platform
# expansion, Lane 3). #380: inverted for Lane 3. A.R.C.H.I.E. is COO and the platform
# is hers, so she is bounded by PROCESS (owner-approved manifest + PR + F.O.R.G.E. +
# window-scoped merge — Tasks 1-4), not by a path allowlist. Codex keeps the narrow
# allowlist (config/agents/codex.yaml) because it is a third-party agent — that scope
# is untouched by this change. The blocked globs are the platform never-touch surface:
# secrets/infra/CI/git internals, THE GOVERNANCE KERNEL (universal — blocked for every
# lane including hers, since it enforces every other rule including which lane runs
# and what gets approved), schema migrations, and the high-risk modules that still
# lack DB isolation.
PLATFORM_SCOPE: dict = {
    "allowed_paths": [
        "platform_v2/",
        "ai_bridge/",
        "scripts/",
        "docs/",
        # NOTE: "database/migrations/" was granted here and REVOKED by owner
        # decision 2026-08-23 — see the blocked glob below for the reasoning.
    ],
    "blocked_globs": [
        "*.env",
        ".env*",
        "*.key",
        "*.pem",
        "*.pfx",
        "secrets/*",
        "docker-compose*",
        "Dockerfile*",
        "scripts/dr/*",
        ".git/*",
        ".github/*",
        # THE GOVERNANCE KERNEL -- universal, blocked for every lane including hers.
        # This code enforces every other rule, including which lane runs and what
        # gets approved. An actor able to rewrite the rules binding it is not
        # governed (decision #953: safety properties are universal).
        "*agent_service.py",
        "*department_dispatcher.py",
        # ...and the MERGE-governance half of that kernel. Lane 3 is bounded by
        # PROCESS (manifest + PR + F.O.R.G.E. + window-scoped merge), so the code
        # IMPLEMENTING that process is precisely what it must not rewrite.
        # github_service holds merge_pr/_automerge_governance_ok/verdict_refusal;
        # pr_review_service holds merge_state/verdict_is_approved/classify_pr_tier.
        "*repair_bay/services/github_service.py",
        "*repair_bay/services/pr_review_service.py",
        # The pre-commit guardrail enforcing the agent single-writer rule.
        "scripts/check_agent_single_writer.py",
        # Lane 2's own harness and sandbox wrapper — cross-lane authority.
        "scripts/agents/*",
        # The single canonical retention pruner: its RETENTION dict is the source
        # of truth for every backup tier, including the off-site DR copies.
        "scripts/backup/*",
        # Schema mutation. Owner decision 2026-08-23: Lane 3 does not author
        # migrations. A migration is largely irreversible once run, and the
        # human who runs it is reviewing SQL, not behaviour — so the PR gate is
        # a weaker check here than it is for application code. Belt AND braces:
        # the allowed_paths grant was removed too, but this glob is what makes
        # the revocation durable — blocked_globs are evaluated FIRST and always
        # win, so re-adding "database/" upstream cannot silently re-grant it.
        "database/migrations/*",
        # Real production data; excluded until they have DB isolation.
        "platform_v2/tools/media_studio/*",
        "platform_v2/tools/game_studio/*",
        "platform_v2/tools/media_hub/*",
    ],
}


def _normalize(path: str) -> Optional[str]:
    """Return a safe repo-relative normalized path, or None if unsafe.

    Rejects absolute paths and anything that escapes the repo via ``..``.
    """
    if not path or not isinstance(path, str):
        return None
    if path.startswith("/"):  # absolute paths are never in scope
        return None
    norm = posixpath.normpath(path)
    # normpath collapses ./ and ../ ; anything still starting with .. escapes the repo
    if norm == "." or norm == ".." or norm.startswith("../") or norm.startswith("/"):
        return None
    return norm


def _clean_prefix(prefix: str) -> Optional[str]:
    """Canonicalize an allowed_paths entry to a safe, boundary-correct prefix.

    Returns a normalized prefix ending in ``/`` so it can only match on a real
    directory boundary, or None for malformed/over-broad entries (which are then
    skipped — fail closed, never allow-all).
    """
    if not prefix or not isinstance(prefix, str):
        return None
    norm = posixpath.normpath(prefix)
    if norm in (".", "/", "..") or norm.startswith("../") or norm.startswith("/"):
        return None
    return norm.rstrip("/") + "/"


def is_in_scope(path: str, cfg: Optional[dict] = None) -> bool:
    """True only if ``path`` is a safe, writable target under the scope config.

    ``cfg`` defaults to :data:`DEFAULT_ARCHIE_CODE_SCOPE`. Fails closed on
    traversal, absolute paths, blocked globs, or anything not under an allowed
    prefix.
    """
    cfg = cfg if cfg is not None else DEFAULT_ARCHIE_CODE_SCOPE
    p = _normalize(path)
    if p is None:
        return False  # traversal / absolute / malformed → denied

    for pat in cfg.get("blocked_globs", []):
        if not pat:
            continue
        # match against the full normalized path AND the basename so "*.env" catches nested
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p.split("/")[-1], pat):
            return False
        if pat.endswith("/*") and p.startswith(pat[:-1]):
            return False

    for prefix in cfg.get("allowed_paths", []):
        cp = _clean_prefix(prefix)
        if cp is None:
            continue  # skip malformed entries — do NOT allow-all on bad config
        # boundary-correct: append "/" so "<allowed>/" must be a real ancestor of the path
        if (p + "/").startswith(cp):
            return True
    return False


def check_diff_paths(paths: Iterable[str], cfg: Optional[dict] = None) -> list[str]:
    """Return the list of out-of-scope paths (empty list == all clean)."""
    cfg = cfg if cfg is not None else DEFAULT_ARCHIE_CODE_SCOPE
    return [p for p in paths if p and not is_in_scope(p, cfg)]
