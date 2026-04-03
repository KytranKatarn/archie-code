"""Inbound HTTP server — accepts work dispatched from ARCHIE hub."""

import logging
from typing import Callable, Awaitable
from aiohttp import web

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


class InboundServer:
    """HTTP server that accepts dispatched work from the hub.

    The hub sends POST /api/dispatch with a task payload.
    Auth is via X-Node-API-Key header (same key returned at registration).
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9091,
                 node_api_key: str | None = None):
        self.host = host
        self.port = port
        self.node_api_key = node_api_key
        self._handler: Callable[[dict], Awaitable[dict]] | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def is_running(self) -> bool:
        return self._site is not None

    def set_job_handler(self, handler: Callable[[dict], Awaitable[dict]]) -> None:
        """Set the callback for processing inbound jobs."""
        self._handler = handler

    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/dispatch", self._handle_dispatch)
        app.router.add_get("/api/health", self._handle_health)
        return app

    async def start(self) -> None:
        app = self._build_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        logger.info("Inbound server listening on http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
        self._runner = None
        self._site = None

    def _verify_auth(self, request: web.Request) -> bool:
        """Verify X-Node-API-Key header matches our stored key."""
        if not self.node_api_key:
            return False
        incoming = request.headers.get("X-Node-API-Key", "")
        return incoming == self.node_api_key

    async def _handle_dispatch(self, request: web.Request) -> web.Response:
        """Handle POST /api/dispatch — process a hub-dispatched job."""
        if not self._verify_auth(request):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON"}, status=400
            )

        task = data.get("task", "").strip()
        if not task:
            return web.json_response(
                {"success": False, "error": "task is required"}, status=400
            )

        if not self._handler:
            return web.json_response(
                {"success": False, "error": "No job handler configured"}, status=503
            )

        try:
            result = await self._handler({
                "task": task,
                "context": data.get("context", {}),
                "source": "hub_dispatch",
                "agent_target": data.get("agent_target"),
                "priority": data.get("priority", 5),
            })
            return web.json_response(result)
        except Exception as e:
            logger.error("Inbound job failed: %s", e)
            return web.json_response(
                {"success": False, "error": str(e)}, status=500
            )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /api/health — basic health check."""
        return web.json_response({
            "status": "ok",
            "engine_version": ENGINE_VERSION,
            "accepting_work": self._handler is not None,
        })
