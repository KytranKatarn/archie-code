"""Hub connector — REST API client for ARCHIE platform."""

import logging
import os

import aiohttp
from archie_engine.hub.auth import HubAuth

# The plan-step DHQ completion is a full LLM call (coder agent) and routinely
# takes 5-30s+ — far longer than the connector's fast control-plane default
# (config.hub_timeout, ~10s). Give it its own generous timeout so the build
# loop's plan step does not time out on F.O.R.G.E. inference (override via
# ARCHIE_DHQ_TIMEOUT). #4256.
try:
    # #4342 Option B: the plan model (qwen2.5-coder:7b) is evicted to the hub CPU tier
    # (8GB Quadro VRAM full) where a structured-plan generation measures ~567s/plan —
    # the old 300s default made the engine bail before the plan returned (0 PRs ever).
    # 900s lets the slow-but-successful hub plan complete. Trade-off: a FAILED plan now
    # takes up to 900s/attempt. Durable fix is GPU-routing the plan (#4342); env-tunable.
    _DHQ_COMPLETE_TIMEOUT = int(os.environ.get("ARCHIE_DHQ_TIMEOUT", "900"))
except (TypeError, ValueError):
    _DHQ_COMPLETE_TIMEOUT = 900  # ignore a malformed override; keep the safe default


def _resolve_timeout(timeout, default):
    """Resolve a per-call timeout for aiohttp.

    A per-call override arrives as int seconds; aiohttp rejects a bare int as a
    session timeout, so wrap it in a ClientTimeout. None → the connector default
    (itself already a ClientTimeout).
    """
    if timeout is None:
        return default
    return aiohttp.ClientTimeout(total=timeout)

logger = logging.getLogger(__name__)


class HubConnector:
    """REST client for the ARCHIE Hub platform."""

    def __init__(self, hub_url: str, auth: HubAuth, timeout: int = 10):
        self.hub_url = hub_url.rstrip("/")
        self.auth = auth
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get(self, path: str, params: dict | None = None) -> dict:
        """HTTP GET with auth headers. Returns parsed JSON or error dict."""
        url = f"{self.hub_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.auth.get_headers(), params=params) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        return {"error": data.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return data
        except Exception as e:
            logger.warning("Hub GET %s failed: %s", path, e)
            return {"error": str(e), "status": 0}

    async def post(self, path: str, data: dict | None = None,
                   timeout: int | None = None) -> dict:
        """HTTP POST with auth headers. Returns parsed JSON or error dict.

        timeout overrides the connector default for this one call (used by
        dhq_complete, whose LLM completion outlasts the fast control-plane default).
        """
        url = f"{self.hub_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=_resolve_timeout(timeout, self.timeout)) as session:
                async with session.post(url, headers=self.auth.get_headers(), json=data) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return result
        except Exception as e:
            logger.warning("Hub POST %s failed: %s", path, e)
            return {"error": str(e), "status": 0}

    # --- Hub Endpoint Methods ---

    async def health_check(self) -> dict:
        """Check hub health (UNAUTHENTICATED — proves reachability only)."""
        return await self.get("/api/archie/health")

    async def auth_check(self) -> dict:
        """AUTHENTICATED reachability probe (#6037).

        `/api/archie/health` requires no auth, so a 200 there proves
        reachability, never authorization — the engine once reported
        "connected" for ten weeks while every authenticated call 401'd, and
        the AUTH_FAILED branch keyed off that probe was unreachable. This
        probes `/api/internal/repair/issues` (``@_require_internal_key``, the
        cheapest read-only internal endpoint the engine already consumes via
        ``fetch_repair_issues``) so a bad credential surfaces as a real 401.
        """
        return await self.get("/api/internal/repair/issues", params={"limit": 1})

    async def register_node(self, node_name: str, hostname: str | None = None,
                            gpu_model: str | None = None, gpu_vram_gb: float | None = None,
                            ram_gb: float | None = None, cpu_cores: int | None = None,
                            cpu_model: str | None = None, os_info: str | None = None,
                            engine_version: str = "0.1.0", inbound_port: int | None = None) -> dict:
        """Register this engine as a node on the hub.

        Sends to /tools/starbase/api/nodes/register (unauthenticated).
        Stores node_id and api_key on success.
        """
        import platform as _platform
        data = {
            "node_name": node_name,
            "hostname": hostname or _platform.node(),
            "gpu_model": gpu_model,
            "gpu_vram_gb": gpu_vram_gb,
            "ram_gb": ram_gb,
            "cpu_cores": cpu_cores,
            "cpu_model": cpu_model,
            "os_info": os_info,
            "client_version": engine_version,
            "description": f"ARCHIE Code engine v{engine_version}",
            "node_type": "starship",
        }
        if inbound_port:
            data["port"] = inbound_port
        url = f"{self.hub_url}/tools/starbase/api/nodes/register"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, json=data, headers={"Content-Type": "application/json"}) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    if result.get("success"):
                        node_id = result.get("node", {}).get("node_id")
                        api_key = result.get("api_key")
                        if node_id:
                            self.auth.store_node_id(node_id)
                        if api_key:
                            self.auth.store_node_key(api_key)
                    return result
        except Exception as e:
            logger.warning("Node registration failed: %s", e)
            return {"error": str(e), "status": 0}

    async def send_heartbeat(self, node_id: str, metrics: dict | None = None) -> dict:
        """Send heartbeat using X-Node-API-Key header."""
        url = f"{self.hub_url}/tools/starbase/api/nodes/{node_id}/heartbeat"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    url, json=metrics or {}, headers=self.auth.get_node_headers(),
                ) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return result
        except Exception as e:
            logger.warning("Heartbeat failed: %s", e)
            return {"error": str(e), "status": 0}

    async def search_knowledge(self, query: str, types: list[str] | None = None,
                               limit: int = 10) -> dict:
        """Search the hub knowledge base via the internal knowledge endpoint."""
        return await self.get("/api/internal/knowledge/search", params={
            "q": query,
            "limit": limit,
        })

    async def dispatch(self, prompt: str, model: str | None = None,
                       agent_target: str | None = None, user_context: dict | None = None) -> dict:
        """Delegate a task to the hub's agent team via the internal delegation
        surface (the modern external→DHQ path; Starbase's /api/archie/chat is gone).

        Non-blocking: submits the task and returns immediately with the task id.
        The Department-HQ dispatcher routes it (welfare/cost/agent selection) and
        the result streams to the platform's Live Dispatch feed + work_notes.
        Returns the router contract {response, agent_name, model} or {error}.
        """
        # agent_target arrives as "capability:<cap>" from the router; map it.
        capability = "code"
        if agent_target:
            capability = agent_target.split(":", 1)[1] if agent_target.startswith("capability:") else agent_target
            capability = capability or "code"
        result = await self.post("/api/internal/delegation/submit", data={
            "capability": capability,
            "reason": prompt,
            "args": user_context or {},
        })
        if "error" in result:
            return result
        task_id = result.get("task_id")
        return {
            "response": (
                f"Delegated to the A.R.C.H.I.E. team as task #{task_id} "
                f"(capability: {capability}). Track it in the Live Dispatch feed."
            ),
            "agent_name": "A.R.C.H.I.E.",
            "model": "delegated",
            "task_id": task_id,
        }

    async def list_agents(self) -> dict:
        """RETIRED (#4265). The /api/starbase/* roster endpoints were removed when
        Starbase merged into Department HQ (2026-04). The engine does not consume the
        hub roster — DHQ selects the agent + model hub-side at dispatch time. Return a
        retired sentinel (no HTTP) so callers skip cleanly instead of hitting a dead
        route that now serves a 200 + HTML login page (and spams JSON-decode warnings)."""
        return {"retired": "starbase agents endpoint removed (DHQ merge 2026-04)"}

    async def get_skills(self) -> dict:
        """RETIRED (#4265) — /api/starbase/skills is gone. (Skill SYNC uses the live
        /tools/consciousness/api/github/skills/sync route, not this method.)"""
        return {"retired": "starbase skills endpoint removed (DHQ merge 2026-04)"}

    async def sync_skills(
        self, since: str | None = None, limit: int = 50
    ) -> dict:
        """Fetch tested skills for sync from hub.

        Args:
            since: ISO timestamp — only skills newer than this
            limit: max skills per response
        """
        params = {"limit": str(limit)}
        if since:
            params["since"] = since
        return await self.get(
            "/tools/consciousness/api/github/skills/sync", params=params
        )

    async def confirm_skill_sync(
        self, skill_ids: list[int], node_id: str = "hub"
    ) -> dict:
        """Confirm successful skill installations to hub."""
        return await self.post(
            "/tools/consciousness/api/github/skills/sync-confirm",
            data={"skill_ids": skill_ids, "node_id": node_id},
        )

    async def get_model_state(self) -> dict:
        """RETIRED (#4265) — /api/starbase/models is gone (DHQ merge 2026-04). The
        engine does not pick models locally; DHQ does that hub-side at dispatch."""
        return {"retired": "starbase models endpoint removed (DHQ merge 2026-04)"}

    async def log_job(self, task: str, agent_name: str,
                      result_summary: str, duration_ms: int,
                      success: bool = True, model: str | None = None,
                      prompt_tokens: int = 0, completion_tokens: int = 0,
                      files_changed: list | None = None,
                      branch: str | None = None) -> dict:
        """Log a completed engine build run to the hub → task_execution_log (#4257).

        Posts to /api/internal/engine/telemetry (the old /api/archie/jobs never
        existed → 404). Uses the connector's existing auth — same INTERNAL_API_KEY
        bearer the engine uses for /api/internal/delegation/submit.
        """
        return await self.post("/api/internal/engine/telemetry", data={
            "task": task,
            "agent_name": agent_name,
            "result_summary": result_summary,
            "duration_ms": duration_ms,
            "success": success,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "files_changed": files_changed,
            "branch": branch,
            "source": "archie-code",
        })

    async def report_build_result(self, task: str, branch: str | None = None,
                                  pr_url: str | None = None, pr_number: int | None = None,
                                  files_changed: list | None = None,
                                  status: str = "completed", duration_ms: int = 0,
                                  tests: list | None = None, output: str = "") -> dict:
        """Report a build/test run to the hub → qa_test_runs/qa_test_results (#4261).

        The engine built + tested in its OWN isolated /workspace; the hub only
        RECORDS the result so engine-driven runs show on the Repair Bay Test Bay +
        QA tabs. Same INTERNAL_API_KEY bearer as the other internal calls.
        """
        return await self.post("/api/internal/engine/build-result", data={
            "task": task,
            "branch": branch,
            "pr_url": pr_url,
            "pr_number": pr_number,
            "files_changed": files_changed,
            "status": status,
            "duration_ms": duration_ms,
            "output": output,
            "tests": tests or [],
        })

    async def code_health_reverify(self, module: str | None = None) -> dict:
        """Loop-closer (#4262): after a deploy, ask Code Health to re-audit and
        confirm the finding actually landed ('fixed') or regressed ('still_open').
        Returns {modules, fixed, still_open, details[]}. Same bearer auth.
        """
        return await self.post(
            "/api/internal/code-health/reverify",
            data={"module": module} if module else {},
        )

    async def record_proposal_pr(
        self, proposal_id: int, pr_number: int, pr_url: str | None = None, branch: str | None = None
    ) -> dict:
        """Record this engine's fix PR on a Repair Bay proposal (spec 2026-08-26 Phase 3).
        POST /api/internal/repair/proposals/<id>/pr -> the proposal flips to pr_open with
        apply_mode='engine_pr', and the hub's merge-completion sweep settles it on merge --
        the engine lane converges with ship_as_pr at ONE completion authority."""
        return await self.post(
            f"/api/internal/repair/proposals/{proposal_id}/pr",
            data={"pr_number": pr_number, "pr_url": pr_url, "branch": branch},
        )

    async def get_repair_proposals(self, status: str = "proposed") -> dict:
        """Read the Repair Bay improvement-proposal work queue (#4259 / #380 pull-work).
        GET /api/internal/repair/proposals?status= → {success, proposals[], count}.
        Same INTERNAL_API_KEY bearer as the other internal reads.
        """
        return await self.get(
            "/api/internal/repair/proposals",
            params={"status": status} if status else None,
        )

    async def get_repair_issues(
        self,
        status: str = "open",
        limit: int = 50,
        auto_fixable: bool = True,
        path_prefixes: list[str] | None = None,
    ) -> dict:
        """Read the open Code-Health issue work queue (#4259).
        GET /api/internal/repair/issues?status=&limit=[&auto_fixable=] → {success, issues[]}.

        auto_fixable defaults to True because the engine IS an automated fixer:
        the hub drops classes that are unsafe or pointless to auto-fix (#5000).

        Why this matters — pull_and_build picks the HIGHEST-SEVERITY in-scope
        issue, and measured 2026-07-19 against 2,230 open issues, 276 of the 286
        open `security/high` findings (96%) were "Potential SQL injection
        vulnerability". That is the same class audit_pipeline already refuses to
        auto-fix because generated fixes were 100% garbage (KB #282665). Without
        this flag the loop draws that class nearly every 6-hourly cycle and burns
        a GPU-gated build slot on it.

        An older hub ignores the unknown query param, so this degrades safely to
        the previous unfiltered behaviour rather than erroring.
        """
        params = {
            "status": status,
            "limit": str(limit),
            "auto_fixable": "true" if auto_fixable else "false",
        }
        if path_prefixes:
            # Server-side scope filter (#5002). We send OUR allowlist so there is one
            # source of truth (scope_guard.PLATFORM_SCOPE) rather than the hub keeping
            # a second copy that can drift. It only NARROWS results — writes remain
            # gated by scope_guard here.
            #
            # Without it the hub returns a severity-ordered window and we filter by
            # path locally: measured 2026-07-19 the first in-scope issue ranked 744
            # against a fetch limit of 200, so every cycle no-opped. With it, all 12
            # in-scope issues come back inside the default limit.
            params["path_prefixes"] = ",".join(p for p in path_prefixes if p)
        return await self.get("/api/internal/repair/issues", params=params)

    async def dhq_complete(self, prompt: str, system_prompt: str | None = None,
                           capability: str | None = None,
                           prefer_agent: str | None = None,
                           module_id: str | None = None,
                           model: str | None = None,
                           format: dict | str | None = None) -> str:
        """Synchronous, strictly-local DHQ completion — for the build loop's plan
        step (#4256). POSTs to /api/internal/dhq/chat, which routes through the
        dispatcher (welfare + cost + cold-load queue, local_only) and returns the
        reply text synchronously. This is the DHQ path — NOT a direct Ollama call.

        Optional capability/prefer_agent/module_id target a specific agent: the
        build loop's plan step sends capability="code"/prefer_agent="F.O.R.G.E."
        so a coder — not the cockpit's A.R.C.H.I.E. conversation voice — writes
        the file-op plan. All three are optional; omitting them keeps the
        endpoint's A.R.C.H.I.E. default.
        """
        payload: dict = {"prompt": prompt, "system_prompt": system_prompt}
        if capability is not None:
            payload["capability"] = capability
        if prefer_agent is not None:
            payload["prefer_agent"] = prefer_agent
        if module_id is not None:
            payload["module_id"] = module_id
        if model is not None:
            payload["model"] = model  # → hub passes as model_override (pins the plan model)
        if format is not None:
            # Structured-output constraint. "json" = bare JSON; a dict = a JSON SCHEMA,
            # which constrains the SHAPE. Added platform-side in archie-platform #2846;
            # before that the hub branch could not express a constraint AT ALL, and an
            # injected source file pulled the model into emitting Python (KB #296229).
            payload["format"] = format
        resp = await self.post("/api/internal/dhq/chat", data=payload,
                               timeout=_DHQ_COMPLETE_TIMEOUT)
        if isinstance(resp, dict):
            # ⚠️ FAIL LOUD. `post()` never raises — it RETURNS {"error": ..., "status": N}.
            # This used to end in `resp.get("response", "") or ""`, so every failure became
            # an EMPTY STRING, indistinguishable from "the model answered nothing".
            #
            # Measured 2026-08-26: three plan attempts spent 903s failing over between a
            # node without the model (404), a node that timed out (600s) and a saturated
            # hub — and the build reported "could not parse a JSON op list from the plan",
            # blaming the MODEL for an infrastructure failure that never reached one. The
            # same masking hid a 401 for ten weeks (#6037): a stale key file shadowed the
            # real credential, every call 401'd in 6ms, and the loop blamed the model then
            # too.
            #
            # The sole production caller (`_plan_dispatch`) is already wrapped by `_plan`'s
            # `except Exception -> "dispatch failed: {exc}"`, which is EXACTLY this signal
            # and never once got the chance to fire.
            err = resp.get("error")
            if err:
                status = resp.get("status")
                raise RuntimeError(
                    f"DHQ dispatch failed (status={status}): {err}"
                )
            return resp.get("response", "") or ""
        # A non-dict is not a failure we can describe; the caller's own retry sees "".
        return ""

    async def get_agent_status(self, agent_id: int) -> dict:
        """RETIRED (#4265) — /api/starbase/agents/<id>/status is gone (DHQ merge 2026-04)."""
        return {"retired": "starbase agent-status endpoint removed (DHQ merge 2026-04)"}

    async def get_personality(self, agent_id: int) -> dict:
        """RETIRED (#4265) — /tools/starbase/api/bridge/agent-personality is gone
        (DHQ merge 2026-04). Engine personality falls back to its baseline."""
        return {"retired": "starbase personality endpoint removed (DHQ merge 2026-04)"}

    async def store_learning(self, knowledge_type: str, title: str,
                             content: str, category: str = "escalation_learning") -> dict:
        """Store a learning in the platform knowledge base via Consciousness."""
        return await self.post("/api/archie/knowledge/store", data={
            "knowledge_type": knowledge_type,
            "title": title,
            "content": content,
            "category": category,
        })
