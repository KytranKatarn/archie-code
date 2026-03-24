"""WebSocket server — accepts JSON messages from TUI/Web clients."""

import asyncio
import json
import logging
from typing import Callable, Awaitable

import websockets
from websockets import serve

logger = logging.getLogger(__name__)


class EngineServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9090):
        self.host = host
        self._requested_port = port
        self.port = port  # may change if port=0
        self._handler: Callable[[dict], Awaitable[dict]] | None = None
        self._server = None
        self._connections: set = set()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def set_handler(self, handler: Callable[[dict], Awaitable[dict]]) -> None:
        """Set the message handler callback (called by Engine)."""
        self._handler = handler

    async def start(self) -> None:
        self._server = await serve(
            self._ws_handler,
            self.host,
            self._requested_port,
        )
        # If port was 0, get the actual port
        for sock in self._server.sockets:
            self.port = sock.getsockname()[1]
            break
        logger.info("WebSocket server listening on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _ws_handler(self, websocket):
        self._connections.add(websocket)
        try:
            async for raw_message in websocket:
                try:
                    msg = json.loads(raw_message)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error", "error": "Invalid JSON"
                    }))
                    continue

                response = await self._process_message(msg)
                await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connections.discard(websocket)

    async def _process_message(self, msg: dict) -> dict:
        msg_type = msg.get("type", "")

        if msg_type == "ping":
            return {"type": "pong"}

        if self._handler:
            try:
                return await self._handler(msg)
            except Exception as e:
                logger.error("Handler error: %s", e)
                return {"type": "error", "error": str(e)}

        return {"type": "error", "error": "No handler configured"}
