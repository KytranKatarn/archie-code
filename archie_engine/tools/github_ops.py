"""GitHub PR operations for the engine — branch+PR-only (ADR-003 / #4255).

The engine opens pull requests against its OWN repo (archie-code) for F.O.R.G.E.
review, and that is its only outward write. There is deliberately NO merge
operation — the engine never merges; a human (or F.O.R.G.E.-gated flow) does.

Guard rails:
  - the target repo is fixed (ADR-003 scope);
  - the head must be a feature branch (never a protected branch);
  - the base must be on the small allowed set (main);
  - a token is required (``ARCHIE_GITHUB_TOKEN`` / ``GITHUB_TOKEN``) — without one
    every write fails closed with a clear error.

The HTTP layer (``_post`` / ``_get``) is isolated so tests can exercise the
guard rails + payload without touching the network.
"""

import os

import aiohttp

from archie_engine.tools.base import BaseTool, ToolResult
from archie_engine.tools.git_ops import PROTECTED_BRANCHES

# Fixed target repo (ADR-003 scope) — "owner/repo" for the GitHub API.
DEFAULT_GITHUB_REPO = os.environ.get("ARCHIE_GITHUB_REPO", "KytranKatarn/archie-code")
GITHUB_API = "https://api.github.com"
ALLOWED_BASES = {"main"}


class GitHubOpsTool(BaseTool):
    name = "github_ops"
    description = "Open a PR for F.O.R.G.E. review (branch+PR-only; never merges)"

    def __init__(self, repo: str = None, token: str = None, api_base: str = GITHUB_API):
        self.repo = repo or DEFAULT_GITHUB_REPO
        self.token = (
            token
            or os.environ.get("ARCHIE_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        self.api_base = api_base

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation", "pr_create")
        if operation == "pr_create":
            return await self._pr_create(
                title=kwargs.get("title"),
                body=kwargs.get("body", ""),
                head=kwargs.get("head"),
                base=kwargs.get("base", "main"),
            )
        elif operation == "pr_get":
            return await self._pr_get(kwargs.get("number"))
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    async def _pr_create(self, title, body, head, base="main") -> ToolResult:
        """Open a PR from a feature branch — the engine's only outward write."""
        if not self.token:
            return ToolResult(success=False, error="no GitHub token (set ARCHIE_GITHUB_TOKEN)")
        if not title or not head:
            return ToolResult(success=False, error="pr_create requires 'title' and 'head'")
        if head in PROTECTED_BRANCHES:
            return ToolResult(
                success=False,
                error=f"head '{head}' is a protected branch — open PRs from feature branches only",
            )
        if base not in ALLOWED_BASES:
            return ToolResult(success=False, error=f"base '{base}' not allowed (only {sorted(ALLOWED_BASES)})")

        payload = {"title": title, "body": body or "", "head": head, "base": base}
        ok, data = await self._post(f"/repos/{self.repo}/pulls", payload)
        if not ok:
            msg = data.get("message") if isinstance(data, dict) else str(data)
            return ToolResult(success=False, error=f"PR create failed: {msg}")
        return ToolResult(
            success=True,
            output=f"Opened PR #{data.get('number')} — {data.get('html_url')}",
            metadata={"number": data.get("number"), "url": data.get("html_url")},
        )

    async def _pr_get(self, number) -> ToolResult:
        """Read a PR's state/mergeable status (read-only — never merges)."""
        if not number:
            return ToolResult(success=False, error="pr_get requires 'number'")
        if not self.token:
            return ToolResult(success=False, error="no GitHub token (set ARCHIE_GITHUB_TOKEN)")
        ok, data = await self._get(f"/repos/{self.repo}/pulls/{number}")
        if not ok:
            msg = data.get("message") if isinstance(data, dict) else str(data)
            return ToolResult(success=False, error=f"PR get failed: {msg}")
        return ToolResult(
            success=True,
            output=f"PR #{number}: state={data.get('state')} mergeable={data.get('mergeable')}",
            metadata={"state": data.get("state"), "mergeable": data.get("mergeable"),
                      "url": data.get("html_url")},
        )

    # ------------------------------------------------------------------
    # HTTP layer — isolated so tests can override it without a network call
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _post(self, path: str, json_body: dict) -> tuple[bool, dict]:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.api_base}{path}", json=json_body,
                                    headers=self._headers()) as resp:
                data = await resp.json()
                return resp.status in (200, 201), data

    async def _get(self, path: str) -> tuple[bool, dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.api_base}{path}", headers=self._headers()) as resp:
                data = await resp.json()
                return resp.status == 200, data
