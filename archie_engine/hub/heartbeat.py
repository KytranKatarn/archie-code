"""Hub heartbeat — registration and keepalive with ARCHIE platform."""

import asyncio
import logging
from archie_engine.hub import HubStatus
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.system_info import get_system_info, get_heartbeat_metrics

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


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
        """Register with hub (or reconnect) and start heartbeat loop."""
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
        """Register this node with the hub, or reconnect using persisted credentials."""
        persisted_id = self.connector.auth.load_node_id()
        persisted_key = self.connector.auth.load_node_key()

        if persisted_id and persisted_key:
            self.node_id = persisted_id
            self.status = HubStatus.CONNECTING
            result = await self.connector.send_heartbeat(
                node_id=persisted_id, metrics=self._build_metrics(),
            )
            if "error" not in result:
                self.status = HubStatus.CONNECTED
                logger.info("Reconnected to hub as node %s", persisted_id)
                return
            elif result.get("status") == 401:
                logger.warning("Persisted credentials rejected — re-registering")
            else:
                logger.warning("Reconnect failed: %s — re-registering", result.get("error"))

        self.status = HubStatus.CONNECTING
        sys_info = get_system_info()
        try:
            result = await self.connector.register_node(
                node_name=f"archie-code-{sys_info['hostname']}",
                hostname=sys_info["hostname"],
                cpu_cores=sys_info["cpu_cores"],
                cpu_model=sys_info.get("cpu_model"),
                ram_gb=sys_info["ram_gb"],
                gpu_model=sys_info.get("gpu_model"),
                gpu_vram_gb=sys_info.get("gpu_vram_gb"),
                os_info=sys_info.get("os_info"),
                engine_version=ENGINE_VERSION,
            )
            if "error" in result:
                if result.get("status") == 401:
                    self.status = HubStatus.AUTH_FAILED
                    logger.error("Hub registration auth failed")
                else:
                    self.status = HubStatus.OFFLINE
                    logger.warning("Hub registration failed: %s", result["error"])
                return

            self.node_id = result.get("node", {}).get("node_id")
            if not self.node_id:
                self.node_id = self.connector.auth.load_node_id()
            self.status = HubStatus.CONNECTED
            logger.info("Registered with hub as node %s", self.node_id)
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Hub registration error: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Background loop sending heartbeats."""
        while True:
            await asyncio.sleep(self.interval)
            await self._send_one_heartbeat()

    async def _send_one_heartbeat(self) -> None:
        """Send a single heartbeat with real system metrics."""
        try:
            result = await self.connector.send_heartbeat(
                node_id=self.node_id or "unknown",
                metrics=self._build_metrics(),
            )
            if "error" in result:
                if result.get("status") == 401:
                    self.status = HubStatus.AUTH_FAILED
                    logger.error("Heartbeat auth failed — stopping")
                    return
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

    def _build_metrics(self) -> dict:
        """Build heartbeat metrics payload."""
        metrics = get_heartbeat_metrics()
        metrics["client_version"] = ENGINE_VERSION
        metrics["ollama_online"] = True
        return metrics
