"""QA operations tool — trigger and inspect P.R.O.B.E. test suites.

Exposes P.R.O.B.E. QA capabilities to archie_engine LLM sessions so they
can list suites, run a suite, or fetch recent run results without needing
MCP access to the A.R.C.H.I.E. platform.

The tool calls the platform's qa_routes HTTP API
(``/tools/repair-bay/api/qa/*``) with form-login credentials. Configure
via environment variables:

- ``ARCHIE_PLATFORM_URL`` (default: http://192.168.1.200:3000)
- ``ARCHIE_API_USERNAME`` (default: admin)
- ``ARCHIE_API_PASSWORD`` (required)

Actions:

- ``list_suites`` — returns all active QA suites
- ``run_suite`` — triggers a run by suite_id or name; returns run_id + totals
- ``get_run`` — returns detail + per-test results for a run_id
- ``recent_runs`` — lists the last N runs (default 10)
"""

import json
import logging
import os

import requests

from archie_engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class QaOpsTool(BaseTool):
    """P.R.O.B.E. QA test suite operations."""

    name = "qa_ops"
    description = (
        "List, run, and inspect P.R.O.B.E. QA test suites via the A.R.C.H.I.E. "
        "platform. Actions: list_suites, run_suite, get_run, recent_runs."
    )

    def __init__(self, platform_url: str = None, username: str = None, password: str = None):
        self.platform_url = (
            platform_url or os.getenv("ARCHIE_PLATFORM_URL", "http://192.168.1.200:3000")
        ).rstrip("/")
        self.username = username or os.getenv("ARCHIE_API_USERNAME", "admin")
        self.password = password or os.getenv("ARCHIE_API_PASSWORD") or os.getenv(
            "ARCHIE_TEST_PASSWORD", ""
        )
        self._session: requests.Session | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        session = requests.Session()
        if not self.password:
            raise RuntimeError(
                "ARCHIE_API_PASSWORD (or ARCHIE_TEST_PASSWORD) not set — "
                "cannot authenticate to platform."
            )
        resp = session.post(
            f"{self.platform_url}/login",
            data={"username": self.username, "password": self.password},
            allow_redirects=False,
            timeout=15,
        )
        # A successful form login returns 302. 200 usually means the login
        # page re-rendered with an error.
        if resp.status_code not in (302, 303):
            raise RuntimeError(
                f"Login failed (HTTP {resp.status_code}) for user={self.username}"
            )
        self._session = session
        return session

    def _api(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated JSON API call. Retries once on 401."""
        session = self._get_session()
        url = f"{self.platform_url}{path}"
        resp = session.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
        if resp.status_code == 401:
            # Session may have expired — re-login once.
            self._session = None
            session = self._get_session()
            resp = session.request(method, url, timeout=30, **kwargs)
        resp.raise_for_status()
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"raw": resp.text}

    # ------------------------------------------------------------------
    # Tool entry point
    # ------------------------------------------------------------------

    async def execute(self, **kwargs) -> ToolResult:
        action = (kwargs.get("action") or "list_suites").strip()
        try:
            if action == "list_suites":
                data = self._api("GET", "/tools/repair-bay/api/qa/suites")
                suites = data.get("suites") or []
                lines = [
                    f"  {s['id']:>3}  {s['name']}  ({s.get('suite_type', '?')})"
                    for s in suites
                ]
                return ToolResult(
                    success=True,
                    output=f"{len(suites)} active QA suite(s):\n" + "\n".join(lines),
                    metadata={"suites": suites},
                )

            if action == "run_suite":
                suite_id = kwargs.get("suite_id")
                suite_name = kwargs.get("suite_name")
                if not suite_id and suite_name:
                    suites = self._api(
                        "GET", "/tools/repair-bay/api/qa/suites"
                    ).get("suites") or []
                    matches = [
                        s for s in suites if s["name"].strip().lower() == suite_name.strip().lower()
                    ]
                    if not matches:
                        return ToolResult(
                            success=False,
                            error=f"No QA suite named '{suite_name}'. Call action=list_suites first.",
                        )
                    suite_id = matches[0]["id"]
                if not suite_id:
                    return ToolResult(
                        success=False,
                        error="run_suite needs suite_id or suite_name",
                    )
                triggered_by = kwargs.get("triggered_by", "archie-cli")
                result = self._api(
                    "POST",
                    f"/tools/repair-bay/api/qa/run/{int(suite_id)}",
                    json={"triggered_by": triggered_by},
                    timeout=kwargs.get("timeout", 900),
                )
                totals = {
                    k: result.get(k)
                    for k in ("run_id", "status", "total", "passed", "failed", "errors")
                }
                return ToolResult(
                    success=bool(result.get("success")),
                    output=(
                        f"Suite {suite_id} run complete: {totals['passed']}/{totals['total']} "
                        f"passed (failed={totals['failed']} errors={totals['errors']}, "
                        f"status={totals['status']}, run_id={totals['run_id']})"
                    ),
                    metadata={"run": totals, "raw": result},
                )

            if action == "get_run":
                run_id = kwargs.get("run_id")
                if not run_id:
                    return ToolResult(success=False, error="get_run needs run_id")
                data = self._api(
                    "GET", f"/tools/repair-bay/api/qa/runs/{int(run_id)}"
                )
                summary = {
                    "run_id": run_id,
                    "status": data.get("status"),
                    "total": data.get("total_tests"),
                    "passed": data.get("passed"),
                    "failed": data.get("failed"),
                    "errors": data.get("errors"),
                    "duration_ms": data.get("duration_ms"),
                }
                return ToolResult(
                    success=True,
                    output=f"Run {run_id}: {summary}",
                    metadata={"run": data},
                )

            if action == "recent_runs":
                limit = int(kwargs.get("limit", 10))
                data = self._api(
                    "GET", f"/tools/repair-bay/api/qa/runs?limit={limit}"
                )
                runs = data.get("runs") or []
                lines = [
                    f"  run {r['id']:>5}  suite={r.get('suite_id')}  "
                    f"{r.get('status'):>10}  passed={r.get('passed')}/{r.get('total_tests')}"
                    for r in runs
                ]
                return ToolResult(
                    success=True,
                    output=f"Last {len(runs)} run(s):\n" + "\n".join(lines),
                    metadata={"runs": runs},
                )

            return ToolResult(
                success=False,
                error=(
                    f"Unknown action '{action}'. "
                    "Use: list_suites, run_suite, get_run, recent_runs."
                ),
            )
        except requests.HTTPError as e:
            return ToolResult(
                success=False,
                error=f"Platform API error: {e} (body: {(e.response.text if e.response else '')[:200]})",
            )
        except Exception as e:
            logger.exception("qa_ops execute failed")
            return ToolResult(success=False, error=f"{type(e).__name__}: {e}")
