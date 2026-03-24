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
        """Get recent message history for a session."""
        return await self.db.fetchall(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        )

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
