"""WebSocket server — accepts JSON messages from TUI/Web clients."""

import asyncio
import inspect
import json
import logging
from typing import Awaitable, Callable

import websockets
from websockets import serve

logger = logging.getLogger(__name__)


class EngineServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9090):
        self.host = host
        self._requested_port = port
        self.port = port  # may change if port=0
        self._handler: Callable[..., Awaitable[dict]] | None = None
        self._handler_wants_send = False
        self._server = None
        self._connections: set = set()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    def set_handler(self, handler: Callable[..., Awaitable[dict]]) -> None:
        """Set the message handler callback (called by Engine).

        A handler MAY optionally accept a second parameter, ``send`` — an async
        callable ``await send(frame: dict)`` used to emit intermediate frames
        (progress streaming) over the same connection BEFORE its final return
        value. Handlers written against the original one-argument contract keep
        working unchanged: the server only passes ``send`` when the handler's
        signature accepts it (detected below). This preserves the legacy
        request->single-response contract that archie-comms and the current TUI
        depend on.
        """
        self._handler = handler
        self._handler_wants_send = self._detect_wants_send(handler)

    @staticmethod
    def _detect_wants_send(handler) -> bool:
        try:
            params = inspect.signature(handler).parameters
        except (TypeError, ValueError):
            return False
        if "send" in params:
            return True
        # A handler declaring **kwargs can also receive send=... .
        return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())

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

        async def send(frame: dict) -> None:
            """Emit one intermediate frame on THIS connection (progress streaming)."""
            await websocket.send(json.dumps(frame))

        try:
            async for raw_message in websocket:
                try:
                    msg = json.loads(raw_message)
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "type": "error", "error": "Invalid JSON"
                    }))
                    continue

                response = await self._process_message(msg, send)
                # A handler may stream via `send` and return None (nothing more to
                # emit); only send a trailing frame when one was returned.
                if response is not None:
                    await websocket.send(json.dumps(response))
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connections.discard(websocket)

    async def _process_message(self, msg: dict, send=None) -> dict | None:
        # A valid-JSON but non-object frame (e.g. `42`, `"hi"`, `[]`) would raise
        # AttributeError on .get below and kill the connection (the surrounding
        # try only catches ConnectionClosed). Return a clean error frame instead.
        if not isinstance(msg, dict):
            return {"type": "error", "error": "message must be a JSON object"}
        msg_type = msg.get("type", "")

        if msg_type == "ping":
            return {"type": "pong"}

        if self._handler:
            try:
                if self._handler_wants_send and send is not None:
                    return await self._handler(msg, send=send)
                return await self._handler(msg)
            except Exception as e:
                logger.error("Handler error: %s", e)
                return {"type": "error", "error": str(e)}

        return {"type": "error", "error": "No handler configured"}
