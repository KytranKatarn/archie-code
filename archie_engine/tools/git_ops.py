"""Git operations tool for the ARCHIE Engine.

Repo lifecycle for the autonomous build loop (#4254): status/diff/log, add,
commit, branch, checkout, pull, push, clone, worktree.

Safety rails enforce the branch+PR-only policy (ADR-003 / #4255):
  - ``push`` REFUSES protected branches (main/master/...) — the engine works on
    feature branches and opens PRs for F.O.R.G.E. review, it never pushes to main.
  - ``add`` is deny-by-default scope-guarded and refuses to stage everything
    (no ``git add -A`` / ``git add .``).
  - ``clone`` is allowlisted to the engine's own repo (archie-code).
  - There is deliberately NO merge / force-push / reset --hard operation.
"""

import asyncio
from pathlib import Path

from archie_engine.tools.base import BaseTool, ToolResult
from archie_engine.scope_guard import is_in_scope

# The engine never pushes directly to these — it opens PRs from feature branches
# for F.O.R.G.E. review (ADR-003, #4255).
PROTECTED_BRANCHES = {"main", "master", "release", "production"}

# Deny-by-default clone allowlist (ADR-003): the engine's autonomous loop is
# scoped to its own repo. Matched by EXACT host/owner/repo — NOT substring (a
# substring check would let a look-alike like "archie-code-evil" through).
ALLOWED_CLONE_REPOS = ("github.com/kytrankatarn/archie-code",)


def _repo_identity(url: str) -> str | None:
    """Reduce a clone URL to its canonical ``host/owner/repo`` (lowercased), or
    None if it doesn't look like a repo URL. Used for exact allowlist matching."""
    s = (url or "").strip().lower()
    for pre in ("https://", "http://", "ssh://"):
        if s.startswith(pre):
            s = s[len(pre):]
            break
    if s.startswith("git@"):
        s = s[4:]
    s = s.replace(":", "/").strip("/")
    if s.endswith(".git"):
        s = s[:-4]
    parts = [p for p in s.split("/") if p]
    if len(parts) < 3:
        return None
    return "/".join(parts[:3])


class GitOpsTool(BaseTool):
    name = "git_ops"
    description = (
        "Git lifecycle — status/diff/log, add, commit, branch, checkout, pull, "
        "push (feature-branch only), clone (allowlisted), worktree"
    )

    def __init__(self, workspace: Path = None, scope_config: dict | None = None):
        self.workspace = workspace or Path.cwd()
        # None → DEFAULT_ARCHIE_CODE_SCOPE inside scope_guard.
        self.scope_config = scope_config

    async def _run_git(self, *args, cwd=None) -> tuple[str, str, int]:
        """Run a git command, returns (stdout, stderr, returncode)."""
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(cwd or self.workspace), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
            proc.returncode,
        )

    async def _current_branch(self) -> str:
        out, _, rc = await self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return out.strip() if rc == 0 else ""

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation", "status")

        if operation == "status":
            return await self._status()
        elif operation == "diff":
            return await self._diff(staged=kwargs.get("staged", False))
        elif operation == "log":
            return await self._log(count=kwargs.get("count", 10))
        elif operation == "add":
            return await self._add(kwargs.get("paths") or kwargs.get("path"))
        elif operation == "commit":
            message = kwargs.get("message")
            if not message:
                return ToolResult(success=False, error="commit requires a 'message' kwarg")
            return await self._commit(message)
        elif operation == "branch":
            return await self._branch(action=kwargs.get("action", "list"), name=kwargs.get("name"))
        elif operation == "checkout":
            return await self._checkout(kwargs.get("ref") or kwargs.get("name"))
        elif operation == "pull":
            return await self._pull(remote=kwargs.get("remote", "origin"), branch=kwargs.get("branch"))
        elif operation == "push":
            return await self._push(remote=kwargs.get("remote", "origin"),
                                    set_upstream=kwargs.get("set_upstream", True))
        elif operation == "clone":
            return await self._clone(kwargs.get("url"), kwargs.get("dest"))
        elif operation == "worktree":
            return await self._worktree(action=kwargs.get("action", "list"),
                                        path=kwargs.get("path"), branch=kwargs.get("branch"))
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    # ------------------------------------------------------------------
    # Read-only
    # ------------------------------------------------------------------

    async def _status(self) -> ToolResult:
        stdout, stderr, rc = await self._run_git("status", "--short")
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout if stdout.strip() else "(clean)")

    async def _diff(self, staged: bool = False) -> ToolResult:
        args = ["diff", "--staged"] if staged else ["diff"]
        stdout, stderr, rc = await self._run_git(*args)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout)

    async def _log(self, count: int = 10) -> ToolResult:
        stdout, stderr, rc = await self._run_git("log", "--oneline", f"-{count}")
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=stdout)

    # ------------------------------------------------------------------
    # Mutations (scope/branch-guarded)
    # ------------------------------------------------------------------

    async def _add(self, paths) -> ToolResult:
        """Stage explicit, in-scope paths only (deny-by-default; never stages all)."""
        # Explicit paths only — never `git add -A`/`.` (could stage out-of-scope
        # files that already exist on disk). Each path is scope-checked.
        if not paths:
            return ToolResult(success=False, error="add requires explicit 'paths' (refusing to stage everything)")
        if isinstance(paths, str):
            paths = [paths]
        out_of_scope = [p for p in paths if not is_in_scope(p, self.scope_config)]
        if out_of_scope:
            return ToolResult(
                success=False,
                error=f"Denied by scope guard: {', '.join(out_of_scope)} outside the engine's writable scope",
            )
        stdout, stderr, rc = await self._run_git("add", "--", *paths)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=f"Staged: {', '.join(paths)}")

    async def _commit(self, message: str) -> ToolResult:
        stdout, stderr, rc = await self._run_git("commit", "-m", message)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip() or stdout.strip())
        return ToolResult(success=True, output=stdout.strip())

    async def _branch(self, action: str = "list", name: str = None) -> ToolResult:
        if action == "list" or name is None:
            stdout, stderr, rc = await self._run_git("branch")
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=stdout)
        elif action == "create":
            stdout, stderr, rc = await self._run_git("checkout", "-b", name)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=(stdout + stderr).strip())
        elif action == "switch":
            stdout, stderr, rc = await self._run_git("checkout", name)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=(stdout + stderr).strip())
        else:
            return ToolResult(success=False, error=f"Unknown branch action: {action}")

    async def _checkout(self, ref) -> ToolResult:
        """Check out an existing branch or commit ref in the workspace."""
        if not ref:
            return ToolResult(success=False, error="checkout requires a 'ref' (branch or commit)")
        stdout, stderr, rc = await self._run_git("checkout", ref)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=(stdout + stderr).strip())

    async def _pull(self, remote: str = "origin", branch: str = None) -> ToolResult:
        """Fast-forward-only pull (never auto-merges divergent history)."""
        # Fast-forward only — never auto-merge divergent history.
        args = ["pull", "--ff-only", remote]
        if branch:
            args.append(branch)
        stdout, stderr, rc = await self._run_git(*args)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=(stdout + stderr).strip())

    async def _push(self, remote: str = "origin", set_upstream: bool = True) -> ToolResult:
        """Push the CURRENT feature branch upstream — refuses protected branches."""
        branch = await self._current_branch()
        if not branch or branch == "HEAD":
            return ToolResult(success=False, error="cannot determine current branch (detached HEAD?)")
        if branch in PROTECTED_BRANCHES:
            return ToolResult(
                success=False,
                error=(
                    f"Refusing to push protected branch '{branch}' — the engine opens PRs "
                    "from feature branches only (ADR-003 / branch+PR-only)."
                ),
            )
        args = ["push"]
        if set_upstream:
            args.append("-u")
        # push the current branch to a same-named remote branch (cannot target main)
        args += [remote, branch]
        stdout, stderr, rc = await self._run_git(*args)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=(stdout + stderr).strip())

    async def _clone(self, url: str, dest: str = None) -> ToolResult:
        """Clone a repo into the workspace — allowlisted by EXACT host/owner/repo."""
        if not url:
            return ToolResult(success=False, error="clone requires a 'url'")
        if _repo_identity(url) not in ALLOWED_CLONE_REPOS:
            return ToolResult(
                success=False,
                error=f"Denied: clone allowlist permits only {ALLOWED_CLONE_REPOS}",
            )
        args = ["clone", url]
        if dest:
            args.append(dest)
        stdout, stderr, rc = await self._run_git(*args)
        if rc != 0:
            return ToolResult(success=False, error=stderr.strip())
        return ToolResult(success=True, output=(stdout + stderr).strip())

    async def _worktree(self, action: str = "list", path: str = None, branch: str = None) -> ToolResult:
        """Manage git worktrees (list / add / remove) for isolated builds."""
        if action == "list":
            stdout, stderr, rc = await self._run_git("worktree", "list")
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=stdout.strip())
        elif action == "add":
            if not path:
                return ToolResult(success=False, error="worktree add requires 'path'")
            args = ["worktree", "add"]
            if branch:
                args += ["-b", branch]
            args.append(path)
            stdout, stderr, rc = await self._run_git(*args)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=(stdout + stderr).strip())
        elif action == "remove":
            if not path:
                return ToolResult(success=False, error="worktree remove requires 'path'")
            stdout, stderr, rc = await self._run_git("worktree", "remove", path)
            if rc != 0:
                return ToolResult(success=False, error=stderr.strip())
            return ToolResult(success=True, output=f"Removed worktree: {path}")
        else:
            return ToolResult(success=False, error=f"Unknown worktree action: {action}")
