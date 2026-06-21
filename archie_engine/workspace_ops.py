"""Workspace ops for the archie-tui coding surface (#4264).

File / git / diff helpers the WebSocket clients (archie-tui) use to drive hands-on
coding against an engine workspace. The TUI is a thin client: it picks a repo root,
browses the file tree, reads files, views git diffs, and applies edits — all executed
here, inside the engine container, against the chosen workspace.

Path safety: every path is resolved UNDER the selected repo root and rejected if it
escapes (defense-in-depth). NOTE: this is the HUMAN-driven surface — the user explicitly
selects a repo + approves each apply, and the ws server binds 127.0.0.1 only. That is a
different trust boundary from scope_guard, which constrains the AUTONOMOUS build loop to
archie-code + blocks self-edits. Here the boundary is "stay within the selected repo root".
"""

from __future__ import annotations

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


def list_repos() -> list[dict]:
    """Workspace roots the engine can operate on (archie-code + archie-platform).

    Resolved from the entrypoint-provisioned env vars; falls back to cwd so the TUI
    always has at least one selectable repo.
    """
    repos: list[dict] = []
    seen: set[str] = set()
    for env, label in (
        ("ARCHIE_ENGINE_WORKSPACE", "archie-code"),
        ("ARCHIE_PLATFORM_WORKSPACE", "archie-platform"),
    ):
        raw = os.getenv(env, "")
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir():
            rp = str(p.resolve())
            if rp not in seen:
                seen.add(rp)
                repos.append({"name": p.name or label, "path": rp, "label": label})
    if not repos:
        cwd = Path.cwd().resolve()
        repos.append({"name": cwd.name, "path": str(cwd), "label": cwd.name})
    return repos


def _safe_root(root: str | None) -> Path:
    """Resolve a repo root, defaulting to cwd. Only an existing directory is honored."""
    if root:
        rp = Path(root).resolve()
        if rp.is_dir():
            return rp
    return Path.cwd().resolve()


def _safe_path(root: Path, rel: str) -> Path:
    """Resolve ``rel`` under ``root``; raise ValueError if it escapes the root."""
    if not rel:
        raise ValueError("empty path")
    target = (Path(rel).resolve() if os.path.isabs(rel) else (root / rel).resolve())
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes repo root: {rel}")
    return target


def file_tree(root: str | None) -> dict:
    """Return a sorted, bounded list of file paths (relative to root)."""
    base = _safe_root(root)
    entries: list[str] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
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


def read_file(root: str | None, path: str) -> dict:
    """Read a file under root (path-safe, byte-bounded)."""
    base = _safe_root(root)
    try:
        target = _safe_path(base, path)
    except ValueError as e:
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
    """Working-tree git diff for the repo (optionally one file)."""
    base = _safe_root(root)
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
    """Apply an edit: write ``content`` to ``path`` under root (path-safe).

    The human picked the repo and approved the apply in the TUI; the only guard here is
    that the target stays within the selected repo root.
    """
    base = _safe_root(root)
    try:
        target = _safe_path(base, path)
    except ValueError as e:
        return {"error": str(e)}
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"root": str(base), "path": path, "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"error": f"write failed: {e}"}
