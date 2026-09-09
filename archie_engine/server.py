"""WebSocket server — accepts JSON messages from TUI/Web clients.

AUTHENTICATION (#6657). Every handshake must carry ``Authorization: Bearer
<ENGINE_WS_TOKEN>``. The check runs in ``process_request`` — BEFORE the message
handler exists for that connection — so an unauthenticated peer gets an HTTP 401
and never reaches the command surface (file_tree / file_read / apply_edit /
shell via ``message`` / build / delegate ...).

Why it exists: the compose deployment binds this server on 0.0.0.0 inside the
``archie_internal`` network, so every container on that network could complete
a handshake. Reproduced 2026-09-09 from ``archie_platform``: ``file_tree
root=/`` listed the engine's root filesystem with no credential at all. The
127.0.0.1-only assumption in ``workspace_ops`` was never true in production.

Fail-CLOSED: with no token configured the server rejects EVERY connection and
logs an error at start. There is deliberately no ``/data`` key-file fallback
(#6037 — a stale file shadowed the env and cost ten weeks of silent 401s).

Origin: browsers cannot set ``Authorization`` on a WebSocket, so a browser can
only ever reach this socket via a proxy that holds the token (archie-comms).
An ``Origin`` header is therefore refused unless it is on
``ENGINE_WS_ALLOWED_ORIGINS`` (default: none) — defence in depth against
cross-site WebSocket hijacking. Non-browser clients (comms with
``suppress_origin=True``, the TUI) send no Origin.
"""

import asyncio
import hmac
import inspect
import json
import logging
import os
from http import HTTPStatus
from typing import Awaitable, Callable

import websockets
from websockets import serve

logger = logging.getLogger(__name__)

TOKEN_ENV = "ENGINE_WS_TOKEN"
ORIGINS_ENV = "ENGINE_WS_ALLOWED_ORIGINS"


def _token_from_env() -> str:
    return (os.environ.get(TOKEN_ENV) or "").strip()


def _origins_from_env() -> set[str]:
    raw = os.environ.get(ORIGINS_ENV) or ""
    return {o.strip() for o in raw.split(",") if o.strip()}


class EngineServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9090,
        token: str | None = None,
        allowed_origins: list[str] | set[str] | None = None,
    ):
        self.host = host
        self._requested_port = port
        self.port = port  # may change if port=0
        self._handler: Callable[..., Awaitable[dict]] | None = None
        self._handler_wants_send = False
        self._server = None
        self._connections: set = set()
        # Explicit arg wins (tests); else env. Empty means "reject everyone".
        self._token = (token if token is not None else _token_from_env()).strip()
        self._allowed_origins = (
            set(allowed_origins) if allowed_origins is not None else _origins_from_env()
        )

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def auth_configured(self) -> bool:
        return bool(self._token)

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

    # ------------------------------------------------------------------ auth --
    def _bearer_ok(self, header_value: str | None) -> bool:
        """Constant-time bearer comparison. Unset server token ⇒ never ok."""
        if not self._token or not header_value:
            return False
        scheme, _, presented = header_value.strip().partition(" ")
        if scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(presented.strip().encode(), self._token.encode())

    def _process_request(self, connection, request):
        """Handshake gate — runs before the connection is accepted.

        Returns ``None`` to accept, or an HTTP response to refuse. The
        ``websockets`` asyncio server (>=14) calls this with
        ``(ServerConnection, Request)``; ``connection.respond`` builds the
        refusal with the right framing for the client's handshake.
        """
        peer = getattr(connection, "remote_address", None)
        if not self._bearer_ok(request.headers.get("Authorization")):
            logger.warning("ws auth rejected from %s (missing/invalid bearer)", peer)
            resp = connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
            resp.headers["WWW-Authenticate"] = 'Bearer realm="archie-engine"'
            return resp
        origin = request.headers.get("Origin")
        if origin is not None and origin not in self._allowed_origins:
            logger.warning("ws origin refused from %s: %s", peer, origin)
            return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed\n")
        return None

    # ------------------------------------------------------------- lifecycle --
    async def start(self) -> None:
        if not self._token:
            logger.error(
                "%s is not set — the engine ws server will REJECT every connection "
                "(fail-closed). Set it in the environment and recreate the container.",
                TOKEN_ENV,
            )
        self._server = await serve(
            self._ws_handler,
            self.host,
            self._requested_port,
            process_request=self._process_request,
        )
        # If port was 0, get the actual port
        for sock in self._server.sockets:
            self.port = sock.getsockname()[1]
            break
        logger.info(
            "WebSocket server listening on ws://%s:%d (bearer auth %s)",
            self.host,
            self.port,
            "on" if self._token else "UNCONFIGURED — rejecting all",
        )

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
