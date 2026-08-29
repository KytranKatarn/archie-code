"""Hub heartbeat — registration and keepalive with ARCHIE platform."""

import asyncio
import logging
from archie_engine.hub import HubStatus
from archie_engine.hub.connector import HubConnector

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
        """Register with hub (or reconnect) and start heartbeat loop.

        The loop starts even when the initial register did not reach the hub:
        ``_send_one_heartbeat`` self-heals OFFLINE -> CONNECTED on each probe, so
        a transient hub outage / DNS blip at engine boot must not permanently
        disable heartbeats (previously the loop only started on CONNECTED, so a
        boot-time outage was unrecoverable for the life of the process). A
        genuine credential failure (AUTH_FAILED) is not retried — it needs a
        config fix, not a spin.
        """
        await self._register()
        if self.status != HubStatus.AUTH_FAILED and not self.is_running:
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
        """Connect to the hub as an authenticated CLIENT (no fleet-node identity).

        The engine is a coding brain that dispatches work to the hub's agent
        team via the internal delegation API — it is NOT an Ollama inference
        node, so it does not register in `remote_nodes`. Connectivity is proven
        by an AUTHENTICATED probe (``auth_check``): a 200 means CONNECTED, a
        401 means AUTH_FAILED, anything else means OFFLINE.

        ⚠️ Must stay ``auth_check``, never ``health_check`` (#6037): the health
        endpoint requires no auth, so probing it reported "connected" for ten
        weeks while every authenticated call 401'd — and the build loop chooses
        the hub branch on this flag. A reachability probe cannot certify
        authorization.
        """
        self.status = HubStatus.CONNECTING
        try:
            result = await self.connector.auth_check()
            if result and "error" not in result:
                self.status = HubStatus.CONNECTED
                logger.info("Connected to hub (client mode via internal key)")
            elif result.get("status") == 401:
                self.status = HubStatus.AUTH_FAILED
                logger.error("Hub auth failed — check ARCHIE_HUB_API_KEY")
            else:
                self.status = HubStatus.OFFLINE
                logger.warning("Hub health check failed: %s", result.get("error"))
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Hub connect error: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Background loop sending heartbeats."""
        while True:
            await asyncio.sleep(self.interval)
            await self._send_one_heartbeat()

    async def _send_one_heartbeat(self) -> None:
        """Keepalive: re-probe the hub (client mode — no node heartbeat).

        Authenticated probe, same as ``_register`` — see the #6037 note there.
        """
        try:
            result = await self.connector.auth_check()
            if result and "error" not in result:
                if self.status == HubStatus.OFFLINE:
                    logger.info("Hub connection restored")
                self.status = HubStatus.CONNECTED
            elif result.get("status") == 401:
                self.status = HubStatus.AUTH_FAILED
                logger.error("Hub auth failed — stopping keepalive")
            else:
                self.status = HubStatus.OFFLINE
                logger.warning("Hub health re-check failed: %s", result.get("error"))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.status = HubStatus.OFFLINE
            logger.warning("Hub keepalive error: %s", e)
