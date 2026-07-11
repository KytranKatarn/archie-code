import json
import logging
import uuid

from archie_engine.database import Database

logger = logging.getLogger(__name__)


class SessionManager:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, working_dir: str) -> dict:
        """Create a new session. Returns session dict with id and working_dir."""
        session_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO sessions (id, working_dir) VALUES (?, ?)",
            (session_id, working_dir),
        )
        await self.db.commit()
        return {"id": session_id, "working_dir": working_dir}

    async def get(self, session_id: str) -> dict | None:
        """Get session by ID."""
        return await self.db.fetchone(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )

    async def add_message(self, session_id: str, role: str, content: str, metadata: dict | None = None) -> int:
        """Add a message to a session. Returns message ID."""
        cursor = await self.db.execute(
            "INSERT INTO messages (session_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (session_id, role, content, json.dumps(metadata or {})),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get the most recent `limit` messages for a session, oldest-first.

        Previously this ordered ASC then LIMIT, which returns the OLDEST N rows —
        so once a session exceeded `limit` messages the history froze on the first
        N and never included new context. Select the newest N by monotonic id,
        then reverse so callers still receive chronological (oldest-first) order.
        """
        rows = await self.db.fetchall(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return list(reversed(rows))

    async def record_tool_call(self, session_id: str, tool_name: str, arguments: dict) -> int:
        """Record a tool call. Returns tool_call ID."""
        cursor = await self.db.execute(
            "INSERT INTO tool_calls (session_id, tool_name, arguments, started_at) VALUES (?, ?, ?, datetime('now'))",
            (session_id, tool_name, json.dumps(arguments)),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def update_tool_result(self, tool_call_id: int, result: str, status: str) -> None:
        """Update a tool call with its result."""
        await self.db.execute(
            "UPDATE tool_calls SET result = ?, status = ?, completed_at = datetime('now') WHERE id = ?",
            (result, status, tool_call_id),
        )
        await self.db.commit()

    async def build_context(self, session_id: str, history_limit: int = 20) -> dict:
        """Build context dict for LLM — session info + recent history."""
        session = await self.get(session_id)
        if not session:
            return {}
        history = await self.get_history(session_id, limit=history_limit)
        return {
            "session_id": session["id"],
            "working_dir": session["working_dir"],
            "history": history,
        }


async def _persist_link(session_id: str, conversation_id: str) -> None:
    """Persist a session<->conversation link on the hub (Task 6). NON-FATAL.

    POSTs to {hub}/api/internal/session-link with the engine's INTERNAL_API_KEY.
    The hub base URL comes from the engine's existing env (ARCHIE_HUB_URL, then
    ARCHIE_PLATFORM_URL). Any failure is logged and swallowed so the local session
    keeps working even when the hub is unreachable.
    """
    import os

    import aiohttp

    hub = os.getenv("ARCHIE_HUB_URL") or os.getenv("ARCHIE_PLATFORM_URL") or "http://192.168.1.200:3000"
    key = os.getenv("INTERNAL_API_KEY", "")
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"{hub.rstrip('/')}/api/internal/session-link",
                json={"session_id": session_id, "conversation_id": conversation_id},
                headers={"Authorization": f"Bearer {key}"},
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                if resp.status != 200:
                    logger.warning("session-link POST -> HTTP %s", resp.status)
    except Exception as exc:  # non-fatal by design
        logger.warning("session-link POST failed (non-fatal): %s", exc)


class Session:
    """A live engine session that can be linked to an archie-comms conversation
    (Task 6). link_conversation stamps the id locally and persists it to the hub
    via the module-level _persist_link (so tests can monkeypatch that seam)."""

    def __init__(self, session_id: str, working_dir: str = "", conversation_id: str | None = None):
        self.session_id = session_id
        self.working_dir = working_dir
        self.conversation_id = conversation_id

    async def link_conversation(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        await _persist_link(self.session_id, conversation_id)
