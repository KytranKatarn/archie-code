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

    async def register_node(self, hostname: str, gpu_model: str | None = None,
                            ram_gb: int | None = None, engine_version: str = "0.1.0") -> dict:
        """Register this engine as a node on the hub."""
        return await self.post("/api/starbase/nodes/register", data={
            "hostname": hostname,
            "gpu_model": gpu_model,
            "ram_gb": ram_gb,
            "engine_version": engine_version,
        })

    async def send_heartbeat(self, node_id: str, metrics: dict | None = None) -> dict:
        """Send heartbeat to keep node registration alive."""
        return await self.post(f"/api/starbase/nodes/{node_id}/heartbeat", data={
            "metrics": metrics or {},
        })

    async def search_knowledge(self, query: str, types: list[str] | None = None,
                               limit: int = 10) -> dict:
        """Search the hub knowledge base."""
        return await self.post("/api/archie/search", data={
            "query": query,
            "types": types,
            "limit": limit,
        })

    async def dispatch(self, prompt: str, model: str | None = None,
                       agent_target: str | None = None, user_context: dict | None = None) -> dict:
        """Dispatch a task through the hub's Bridge."""
        return await self.post("/api/archie/chat", data={
            "prompt": prompt,
            "model": model,
            "agent_target": agent_target,
            "user_context": user_context or {},
        })

    async def list_agents(self) -> dict:
        """List available agents on the hub."""
        return await self.get("/api/starbase/agents")

    async def get_skills(self) -> dict:
        """Get available skills from the hub."""
        return await self.get("/api/starbase/skills")

    async def get_model_state(self) -> dict:
        """Get current model load state from the hub."""
        return await self.get("/api/starbase/models")

    async def log_job(self, task: str, agent_name: str,
                      result_summary: str, duration_ms: int) -> dict:
        """Log a completed job to the hub for activity tracking."""
        return await self.post("/api/archie/jobs", data={
            "task": task,
            "agent_name": agent_name,
            "result_summary": result_summary,
            "duration_ms": duration_ms,
            "source": "archie-code",
        })

    async def get_agent_status(self, agent_id: int) -> dict:
        """Get current status of a specific agent."""
        return await self.get(f"/api/starbase/agents/{agent_id}/status")

    async def store_learning(self, knowledge_type: str, title: str,
                             content: str, category: str = "escalation_learning") -> dict:
        """Store a learning in the platform knowledge base via Consciousness."""
        return await self.post("/api/archie/knowledge/store", data={
            "knowledge_type": knowledge_type,
            "title": title,
            "content": content,
            "category": category,
        })
