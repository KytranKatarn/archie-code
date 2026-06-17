"""Hub connector — REST API client for ARCHIE platform."""

import logging
import aiohttp
from archie_engine.hub.auth import HubAuth

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

    async def post(self, path: str, data: dict | None = None) -> dict:
        """HTTP POST with auth headers. Returns parsed JSON or error dict."""
        url = f"{self.hub_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
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
        """Check hub health."""
        return await self.get("/api/archie/health")

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
        """List available agents on the hub."""
        return await self.get("/api/starbase/agents")

    async def get_skills(self) -> dict:
        """Get available skills from the hub."""
        return await self.get("/api/starbase/skills")

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
        """Get current model load state from the hub."""
        return await self.get("/api/starbase/models")

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

    async def dhq_complete(self, prompt: str, system_prompt: str | None = None) -> str:
        """Synchronous, strictly-local DHQ completion — for the build loop's plan
        step (#4256). POSTs to /api/internal/dhq/chat, which routes through the
        dispatcher (welfare + cost + cold-load queue, local_only) and returns the
        reply text synchronously. This is the DHQ path — NOT a direct Ollama call.
        """
        resp = await self.post("/api/internal/dhq/chat",
                               data={"prompt": prompt, "system_prompt": system_prompt})
        if isinstance(resp, dict):
            return resp.get("response", "") or ""
        return ""

    async def get_agent_status(self, agent_id: int) -> dict:
        """Get current status of a specific agent."""
        return await self.get(f"/api/starbase/agents/{agent_id}/status")

    async def get_personality(self, agent_id: int) -> dict:
        """Get personality, mood, and relationship data for an agent."""
        return await self.get(f"/tools/starbase/api/bridge/agent-personality/{agent_id}")

    async def store_learning(self, knowledge_type: str, title: str,
                             content: str, category: str = "escalation_learning") -> dict:
        """Store a learning in the platform knowledge base via Consciousness."""
        return await self.post("/api/archie/knowledge/store", data={
            "knowledge_type": knowledge_type,
            "title": title,
            "content": content,
            "category": category,
        })
