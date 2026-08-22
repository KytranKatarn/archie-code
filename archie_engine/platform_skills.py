"""#5333 skill bridge -- the PLATFORM's invokable-skills registry, proxied for the TUI.

Distinct from ``engine.skill_registry.list_skills()``, which lists the engine's OWN
local skills. This module exposes the hub's registry: known-tool delegates (no LLM)
plus every LLM capability in CAPABILITY_DEPARTMENT_MAP, so archie-tui can list and
fire the same work Claude fires -- sovereign-local on the cluster, through DHQ.

Transport rules that are NOT optional here:
  * Mesh only. ARCHIE_HUB_URL is 100.64.0.4:3000 in compose. A public hostname
    would hit the 60s CDN cap and bypass the dispatch queue.
  * Every invocation is an INSERT through the hub's existing delegation surface
    (submit -> delegate_task_worker -> department_dispatcher). No new execution
    machinery, and NO direct Ollama anywhere in this path (ADR-013).

Everything here is fail-soft: a hub that is down or slow returns ``{"error": ...}``
so the palette shows a message. Raising would kill the websocket connection and
take the whole TUI down with it.
"""

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The TUI is the surface these calls originate from. #5291 added 'tui' to the
# platform's VALID_DELEGATION_SOURCES; #5333 made submit actually honour it
# (it hardcoded 'web_chat' before, so every TUI action was mis-attributed).
DELEGATION_SOURCE = "tui"

_REGISTRY_PATH = "/api/internal/delegation/invokable-skills"
_SUBMIT_PATH = "/api/internal/delegation/submit"
_STATUS_PATH = "/api/internal/delegation/{task_id}/status"

# The registry is a pure read of two in-process dicts on the hub; a slow answer
# means the hub is unwell, not that the list is big. Submit is a single INSERT.
_TIMEOUT_S = 10


def hub_base() -> str:
    """Hub base URL, matching the precedence session._persist_link already uses."""
    return (
        os.getenv("ARCHIE_HUB_URL")
        or os.getenv("ARCHIE_PLATFORM_URL")
        or "http://100.64.0.4:3000"
    ).rstrip("/")


def _auth_headers() -> dict:
    # ARCHIE_HUB_API_KEY and INTERNAL_API_KEY are set to the SAME value in compose;
    # accept either so the engine still authenticates if one is dropped.
    key = os.getenv("INTERNAL_API_KEY") or os.getenv("ARCHIE_HUB_API_KEY") or ""
    return {"Authorization": f"Bearer {key}"}


async def _request(method: str, path: str, payload: Optional[dict] = None) -> dict:
    """One hub round-trip. Never raises -- returns {"error": ...} instead."""
    import aiohttp

    url = f"{hub_base()}{path}"
    try:
        async with aiohttp.ClientSession() as http:
            async with http.request(
                method,
                url,
                json=payload,
                headers=_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=_TIMEOUT_S),
            ) as resp:
                # Read the body regardless of status: the hub reports WHY in JSON
                # (e.g. an invalid delegation_source -> 400 with the valid set),
                # and discarding that turns a fixable message into a bare number.
                try:
                    body = await resp.json()
                except Exception:
                    body = {"error": (await resp.text())[:200]}
                if resp.status >= 400:
                    detail = body.get("error") if isinstance(body, dict) else None
                    return {"error": detail or f"hub returned HTTP {resp.status}", "status": resp.status}
                return body if isinstance(body, dict) else {"error": "hub returned a non-object body"}
    except Exception as exc:
        logger.warning("platform_skills %s %s failed: %s", method, path, exc)
        return {"error": f"hub unreachable: {exc}"}


async def list_platform_skills() -> dict:
    """The registry: {"skills": [...], "known_tool_count": n, "llm_count": n}."""
    return await _request("GET", _REGISTRY_PATH)


async def invoke_platform_skill(
    capability: str,
    reason: str,
    args: Optional[dict] = None,
    priority: int = 5,
    source: str = DELEGATION_SOURCE,
) -> dict:
    """Fire one skill. Returns {"task_id": int, "status": "queued", ...}.

    Validation of ``capability`` is deliberately left to the hub: it owns the
    registry, so a check here would be a second source of truth that goes stale
    the moment a capability is added. ``reason`` IS checked locally only because
    an empty one is a client bug the hub would answer with a bare 400.
    """
    if not capability or not str(capability).strip():
        return {"error": "capability is required"}
    if not reason or not str(reason).strip():
        return {"error": "reason is required"}
    return await _request(
        "POST",
        _SUBMIT_PATH,
        {
            "capability": str(capability).strip(),
            "reason": str(reason).strip(),
            "args": args or {},
            "priority": priority,
            "delegation_source": source,
        },
    )


async def platform_skill_status(task_id: Any) -> dict:
    """Poll one delegated task: {"status": ..., "work_notes": ...}."""
    try:
        tid = int(task_id)
    except (TypeError, ValueError):
        return {"error": f"invalid task_id: {task_id!r}"}
    return await _request("GET", _STATUS_PATH.format(task_id=tid))
