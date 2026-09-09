"""Workspace ops for the archie-tui coding surface (#4264) — CONFINED (#6657).

File / git / diff helpers the WebSocket clients (archie-tui, archie-comms) use to
drive hands-on coding against an engine workspace. The client picks a repo root,
browses the file tree, reads files, views git diffs, and applies edits — all executed
here, inside the engine container.

TRUST BOUNDARY (rewritten 2026-09-09). The previous docstring said the ws server
"binds 127.0.0.1 only" and therefore let a client name ANY existing directory as
its root. In the compose deployment the server binds 0.0.0.0 on ``archie_internal``
and was reachable from every container; ``file_tree root=/`` listed the engine's
root filesystem. Two rules now apply, in this order:

1. ROOT ALLOWLIST — a root is accepted only if it is (or lies under) one of
   :func:`allowed_roots`: ``ARCHIE_ENGINE_WORKSPACE``, ``ARCHIE_PLATFORM_WORKSPACE``
   and the optional CSV ``ARCHIE_ENGINE_WS_ROOTS``. When NONE of those is set (a
   dev/test process, never the container) the process cwd is the single root.
2. SECRET DENY — inside an allowed root, credential-shaped paths are refused for
   read, list, diff AND write: ``.env``-family files, key material, ``.git/``,
   ``secrets/``, ``credentials/`` ... (see ``_SECRET_DIRS`` / ``_SECRET_NAMES``).

Every op reports a refusal as ``{"error": ...}`` — the ws handler must never see
an exception from here. This is distinct from ``scope_guard``, which constrains
the AUTONOMOUS build loop's writes; this module is the human/proxy-driven surface.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path

# Bounds — keep ws responses small and safe.
MAX_TREE_ENTRIES = 2000
MAX_FILE_BYTES = 200_000
MAX_DIFF_BYTES = 200_000
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

ROOT_ENVS: tuple[tuple[str, str], ...] = (
    ("ARCHIE_ENGINE_WORKSPACE", "archie-code"),
    ("ARCHIE_PLATFORM_WORKSPACE", "archie-platform"),
)
EXTRA_ROOTS_ENV = "ARCHIE_ENGINE_WS_ROOTS"

# Directory names that are never listed/read/written through this surface.
_SECRET_DIRS = {".git", "secrets", "credentials", ".ssh", ".gnupg", ".aws"}
# File-name patterns (fnmatch, case-sensitive) that are never read/written/diffed.
_SECRET_NAMES = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git-credentials",
    ".hub_key",
    ".node_key",
    "*.secret",
    "*.token",
)


def allowed_roots() -> list[Path]:
    """Resolved directories a client may operate on, in priority order.

    Env-configured roots only; the cwd fallback exists so an un-configured dev
    process still has one root, and it is never taken in the container (compose
    sets both workspace vars).
    """
    roots: list[Path] = []
    seen: set[str] = set()
    candidates: list[str] = [os.getenv(env, "") for env, _label in ROOT_ENVS]
    candidates += [c for c in os.getenv(EXTRA_ROOTS_ENV, "").split(",")]
    for raw in candidates:
        raw = raw.strip()
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir():
            rp = p.resolve()
            if str(rp) not in seen:
                seen.add(str(rp))
                roots.append(rp)
    if not roots:
        roots.append(Path.cwd().resolve())
    return roots


def list_repos() -> list[dict]:
    """Workspace roots the engine can operate on — exactly :func:`allowed_roots`.

    Advertising anything else would offer the TUI a root that every op then refuses.
    """
    labels = {os.getenv(env, ""): label for env, label in ROOT_ENVS}
    repos: list[dict] = []
    for rp in allowed_roots():
        label = next((lbl for raw, lbl in labels.items() if raw and Path(raw).resolve() == rp), rp.name)
        repos.append({"name": rp.name or label, "path": str(rp), "label": label})
    return repos


def _is_under(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _safe_root(root: str | None, *, trusted_root: bool = False) -> Path:
    """Resolve the repo root a client asked for, or raise PermissionError.

    ``None``/empty → the first allowed root. Anything else must resolve to an
    existing directory that is one of, or lies under, the allowed roots.

    ``trusted_root=True`` is for ENGINE-INTERNAL callers whose root comes from
    config (e.g. ``config.platform_workspace`` in ``Engine._finding_is_stale``),
    never from a ws/MCP client: the allowlist is skipped, the escape check and
    the secret deny in :func:`_safe_path` still apply. Grep for it before adding
    a call site — a client-supplied root must never reach this flag.
    """
    if not root:
        return allowed_roots()[0]
    rp = Path(root).resolve()
    if not rp.is_dir():
        raise PermissionError(f"root is not a directory: {root}")
    if not trusted_root and not any(_is_under(rp, r) for r in allowed_roots()):
        raise PermissionError(f"root outside allowed workspaces: {root}")
    return rp


def _is_secret_path(root: Path, target: Path) -> bool:
    """True when ``target`` (already resolved, under ``root``) is credential-shaped."""
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        return True  # not under root at all — never a legitimate target
    if not parts:
        return False
    if any(part in _SECRET_DIRS for part in parts[:-1]) or parts[-1] in _SECRET_DIRS:
        return True
    name = parts[-1]
    return any(fnmatch.fnmatchcase(name, pat) for pat in _SECRET_NAMES)


def _safe_path(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``; raise ValueError if it escapes or is secret."""
    if not rel:
        raise ValueError("empty path")
    target = (Path(rel).resolve() if os.path.isabs(rel) else (root / rel).resolve())
    if not _is_under(target, root):
        raise ValueError(f"path escapes repo root: {rel}")
    if _is_secret_path(root, target):
        raise ValueError(f"secret path denied: {rel}")
    return target


def file_tree(root: str | None) -> dict:
    """Return a sorted, bounded list of file paths (relative to root); secrets omitted."""
    try:
        base = _safe_root(root)
    except PermissionError as e:
        return {"error": str(e)}
    entries: list[str] = []
    truncated = False
    skip = _SKIP_DIRS | _SECRET_DIRS
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if any(fnmatch.fnmatchcase(fn, pat) for pat in _SECRET_NAMES):
                continue
            full = Path(dirpath) / fn
            try:
                entries.append(str(full.relative_to(base)))
            except ValueError:
                continue
            if len(entries) >= MAX_TREE_ENTRIES:
                truncated = True
                break
        if truncated:
            break
    entries.sort()
    return {"root": str(base), "files": entries, "truncated": truncated}


def read_file(root: str | None, path: str, *, trusted_root: bool = False) -> dict:
    """Read a file under an allowed root (path-safe, secret-denied, byte-bounded).

    ``trusted_root`` — see :func:`_safe_root`; engine-internal, config-sourced roots only.
    """
    try:
        base = _safe_root(root, trusted_root=trusted_root)
        target = _safe_path(base, path)
    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    if not target.is_file():
        return {"error": f"not a file: {path}"}
    raw = target.read_bytes()
    return {
        "root": str(base),
        "path": path,
        "content": raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace"),
        "truncated": len(raw) > MAX_FILE_BYTES,
    }


def git_diff(root: str | None, path: str | None = None) -> dict:
    """Working-tree git diff for the repo (optionally one file, secret-denied)."""
    try:
        base = _safe_root(root)
        if path:
            _safe_path(base, path)
    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    cmd = ["git", "-C", str(base), "diff"]
    if path:
        cmd += ["--", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        full = out.stdout or ""
        return {
            "root": str(base),
            "path": path,
            "diff": full[:MAX_DIFF_BYTES],
            "truncated": len(full) > MAX_DIFF_BYTES,
        }
    except Exception as e:  # diff must never crash the ws handler
        return {"error": f"git diff failed: {e}"}


def write_file(root: str | None, path: str, content: str) -> dict:
    """Apply an approved edit: write ``content`` to ``path`` under an allowed root.

    Re-validates root + path at write time (the approval may be minutes old and the
    allowlist is the boundary, not the approval).
    """
    try:
        base = _safe_root(root)
        target = _safe_path(base, path)
    except (PermissionError, ValueError) as e:
        return {"error": str(e)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"root": str(base), "path": path, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"error": f"write failed: {e}"}
