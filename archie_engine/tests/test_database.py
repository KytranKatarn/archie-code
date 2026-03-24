import pytest
import pytest_asyncio
from pathlib import Path
from archie_engine.database import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_initialize_creates_tables(db):
    """sessions, messages, tool_calls tables exist after init."""
    tables = await db.list_tables()
    assert "sessions" in tables
    assert "messages" in tables
    assert "tool_calls" in tables


@pytest.mark.asyncio
async def test_schema_version(db):
    """Schema version is >= 1."""
    version = await db.get_schema_version()
    assert version >= 1


@pytest.mark.asyncio
async def test_insert_and_fetch_message(db):
    """Insert session + message, fetch back, verify fields."""
    # Insert session
    await db.execute(
        "INSERT INTO sessions (id, working_dir) VALUES (?, ?)",
        ("sess-001", "/tmp/work"),
    )
    await db.commit()

    # Insert message
    await db.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        ("sess-001", "user", "Hello, ARCHIE!"),
    )
    await db.commit()

    # Fetch back
    row = await db.fetchone(
        "SELECT * FROM messages WHERE session_id = ?", ("sess-001",)
    )
    assert row is not None
    assert row["session_id"] == "sess-001"
    assert row["role"] == "user"
    assert row["content"] == "Hello, ARCHIE!"

    # Also verify fetchall works
    rows = await db.fetchall(
        "SELECT * FROM messages WHERE session_id = ?", ("sess-001",)
    )
    assert len(rows) == 1
    assert rows[0]["content"] == "Hello, ARCHIE!"
