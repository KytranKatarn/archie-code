"""Dev HQ projects and tasks, for archie-tui.

Until now the engine was WRITE-ONLY and BLIND on Dev HQ: every delegation it submits
creates a `unified_tasks` row (delegation_source='tui'), but it had no way to list,
read or close anything. The 5 tui-sourced tasks it opened sat unclosed from
2026-08-23 for exactly that reason.

The hub already exposes the full API behind `@require_internal_scope("tasks:read")` /
`("tasks:write")`; archie-platform grants `archie_engine` both. Nothing is reimplemented
here — this is a client.

Every function returns a dict and NEVER raises, matching platform_skills: a hub that is
down or a scope that was not granted must degrade the TUI, not crash the engine. A
refusal arrives as {"error": ...} and is shown, not swallowed.
"""

from typing import Any, Optional
from urllib.parse import quote, urlencode

# Reuse the ONE authenticated round-trip helper rather than duplicating bearer handling.
# It reads INTERNAL_API_KEY / ARCHIE_HUB_API_KEY and never raises.
from archie_engine.platform_skills import _request


def _qs(**params: Any) -> str:
    """Query string from the non-empty params only."""
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return ("?" + urlencode(clean)) if clean else ""


async def list_projects(status: Optional[str] = None, limit: int = 25) -> dict:
    """Dev HQ projects. Find the project BEFORE creating a task so work lands parented."""
    return await _request("GET", "/api/internal/projects" + _qs(status=status, limit=limit))


async def list_tasks(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    min_priority: Optional[int] = None,
    limit: int = 25,
) -> dict:
    """Dev HQ tasks. Check what is already open before starting work — duplicate tasks
    for one piece of work are a recurring problem on this platform."""
    return await _request(
        "GET",
        "/api/internal/tasks"
        + _qs(project_id=project_id, status=status, q=q, min_priority=min_priority, limit=limit),
    )


async def get_task(task_id: Any) -> dict:
    """One task in full, including its description."""
    return await _request("GET", "/api/internal/tasks/%s" % quote(str(task_id)))


async def create_task(
    project_id: Any, title: str, description: str = "", priority: int = 5
) -> dict:
    """Create a Dev HQ task. `priority` is an INTEGER 1-10, not a word."""
    return await _request(
        "POST",
        "/api/internal/tasks",
        {
            "project_id": project_id,
            "title": title,
            "description": description,
            "priority": priority,
        },
    )


async def set_task_status(task_id: Any, status: str) -> dict:
    """Update a task's status — this is how the TUI CLOSES its own work."""
    return await _request(
        "POST", "/api/internal/tasks/%s/status" % quote(str(task_id)), {"status": status}
    )


async def add_task_note(task_id: Any, note: str) -> dict:
    """Append a work note. A closed task with no note is not a record anyone can use."""
    return await _request(
        "POST", "/api/internal/tasks/%s/note" % quote(str(task_id)), {"note": note}
    )
