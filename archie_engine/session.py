import json
import uuid
from archie_engine.database import Database


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

    async def link_conversation(self, session_id: str, conversation_id: str) -> dict:
        """Link an engine session to an archie-comms conversation (Task 6).

        Establishes the handle the MCP session_send tool uses to route a message
        from Claude into the linked conversation. Idempotent — re-linking updates
        the existing row (one conversation per session). Returns the link record,
        or {"error": ...} when the session does not exist.
        """
        session = await self.get(session_id)
        if not session:
            return {"error": f"session not found: {session_id}"}
        await self._persist_link(session_id, conversation_id)
        return {"session_id": session_id, "conversation_id": conversation_id}

    async def _persist_link(self, session_id: str, conversation_id: str) -> None:
        """Upsert the session<->conversation link row (Task 6)."""
        await self.db.execute(
            "INSERT INTO conversation_links (session_id, conversation_id, linked_at) "
            "VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "conversation_id = excluded.conversation_id, linked_at = datetime('now')",
            (session_id, conversation_id),
        )
        await self.db.commit()

    async def get_linked_conversation(self, session_id: str) -> str | None:
        """Return the conversation_id linked to a session, or None (Task 6)."""
        row = await self.db.fetchone(
            "SELECT conversation_id FROM conversation_links WHERE session_id = ?",
            (session_id,),
        )
        return row["conversation_id"] if row else None
