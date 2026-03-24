"""Hub heartbeat — registration and keepalive with ARCHIE platform."""

import asyncio
import logging
import platform
from archie_engine.hub import HubStatus
from archie_engine.hub.connector import HubConnector

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, connector: HubConnector, interval: int = 30):
        self.connector = connector
        self.interval = interval
        self.status = HubStatus.DISCONNECTED
        self.node_id: str | None = None
        self._task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Register with hub and start heartbeat loop."""
        await self._register()
        if self.status == HubStatus.CONNECTED:
            self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        """Stop heartbeat loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _register(self) -> None:
        """Register this node with the hub."""
        self.status = HubStatus.CONNECTING
        try:
            result = await self.connector.register_node(
                hostname=platform.node(),
            )
            if "error" in result:
                if result.get("status") == 401:
                    self.status = HubStatus.AUTH_FAILED
                    logger.error("Hub auth failed — check API key")
                else:
                    self.status = HubStatus.OFFLINE
                    logger.warning("Hub registration failed: %s", result["error"])
                return

            self.node_id = result.get("node_id")
            self.status = HubStatus.CONNECTED
            logger.info("Registered with hub as node %s", self.node_id)
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Hub registration error: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Background loop sending heartbeats."""
        while True:
            await asyncio.sleep(self.interval)
            try:
                result = await self.connector.send_heartbeat(
                    node_id=self.node_id or "unknown",
                    metrics={"status": "active"},
                )
                if "error" in result:
                    if result.get("status") == 401:
                        self.status = HubStatus.AUTH_FAILED
                        logger.error("Heartbeat auth failed")
                        return  # Stop heartbeating
                    self.status = HubStatus.OFFLINE
                    logger.warning("Heartbeat failed: %s", result["error"])
                else:
                    if self.status == HubStatus.OFFLINE:
                        logger.info("Hub connection restored")
                    self.status = HubStatus.CONNECTED
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status = HubStatus.OFFLINE
                logger.warning("Heartbeat error: %s", e)
