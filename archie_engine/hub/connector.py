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
