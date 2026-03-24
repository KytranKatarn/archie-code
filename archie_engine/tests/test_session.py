import pytest
import pytest_asyncio
from archie_engine.database import Database
from archie_engine.session import SessionManager


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def session_mgr(db):
    return SessionManager(db)


@pytest.mark.asyncio
async def test_create_session(session_mgr):
    session = await session_mgr.create(working_dir="/tmp/project")
    assert session["id"] is not None
    assert session["working_dir"] == "/tmp/project"


@pytest.mark.asyncio
async def test_resume_session(session_mgr):
    created = await session_mgr.create(working_dir="/tmp/project")
    resumed = await session_mgr.get(created["id"])
    assert resumed is not None
    assert resumed["id"] == created["id"]


@pytest.mark.asyncio
async def test_add_message(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    await session_mgr.add_message(session["id"], role="user", content="hello")
    await session_mgr.add_message(session["id"], role="assistant", content="hi!")
    history = await session_mgr.get_history(session["id"])
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_history_limit(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    for i in range(20):
        await session_mgr.add_message(session["id"], "user", f"msg {i}")
    history = await session_mgr.get_history(session["id"], limit=5)
    assert len(history) == 5


@pytest.mark.asyncio
async def test_record_tool_call(session_mgr):
    session = await session_mgr.create(working_dir="/tmp")
    tool_id = await session_mgr.record_tool_call(
        session_id=session["id"],
        tool_name="file_ops",
        arguments={"operation": "read", "path": "test.py"},
    )
    assert tool_id is not None


@pytest.mark.asyncio
async def test_build_context(session_mgr):
    session = await session_mgr.create(working_dir="/tmp/myproject")
    await session_mgr.add_message(session["id"], "user", "fix the bug")
    context = await session_mgr.build_context(session["id"])
    assert context["working_dir"] == "/tmp/myproject"
    assert len(context["history"]) == 1
