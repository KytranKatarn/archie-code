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
# expansion). Mirrors the PROVEN codex allowlist (config/agents/codex.yaml): only the
# low-data Applications/Concepts modules + their shared-tree UI + tests.
# media_studio/game_studio/media_hub are deliberately EXCLUDED — they hold real prod
# data and need DB isolation first (same call codex made). The blocked globs add the
# platform never-touch surface (secrets/infra/CI + the agent/dispatch core) on top.
PLATFORM_SCOPE: dict = {
    "allowed_paths": [
        "platform_v2/tools/fitness/",
        "platform_v2/tools/family_tree/",
        "platform_v2/tools/therapy/",
        "platform_v2/tools/faith/",
        "platform_v2/tools/brainstorm/",
        "platform_v2/tools/doc/",
        "platform_v2/templates/tools/fitness.html",
        "platform_v2/templates/tools/therapy.html",
        "platform_v2/templates/tools/faith.html",
        "platform_v2/templates/tools/brainstorm.html",
        "platform_v2/templates/tools/doc.html",
        "platform_v2/static/js/fitness-chat.js",
        "platform_v2/static/js/therapy-chat.js",
        "platform_v2/static/js/faith-chat.js",
        "platform_v2/static/js/family-tree-chat.js",
        "platform_v2/static/js/doc-chat.js",
        "platform_v2/static/css/fitness.css",
        "platform_v2/static/css/therapy.css",
        "platform_v2/tests/",
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
        # never let autonomous platform edits touch the agent/dispatch core
        "*agent_service.py",
        "*department_dispatcher.py",
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
