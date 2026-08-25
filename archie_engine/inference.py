"""Inference client for ARCHIE Engine — DHQ dispatcher first, local fallback.

## Why this routes through the hub (ADR-013)

Every completion here now goes through the hub endpoint ``/api/internal/dhq/chat``,
which calls ``department_dispatcher.dispatch()`` on the platform side with
``local_only=True``. Lane 3 previously called the hub's model server directly.
Measured 2026-08-25, that meant it:

  * bypassed the dispatcher entirely, in violation of ADR-013
  * was PINNED TO THE HUB — measured that day at 45% success / 422s average on
    ``code_review``, while USS-246 ran 73% and USS-245 **98%**. Lane 3 could reach
    neither, because it never asked the dispatcher where to run.
  * got no welfare gating, no cold-load queue, no capability routing
  * never appeared in ``task_execution_log``, so it was invisible to Token Economy and
    A.R.M.A.D.A. — the platform could not see its own builder working

The endpoint was built for exactly this caller (#4256) and never adopted. It returns 502
when dispatch produces nothing, precisely so the caller can fall back.

## The fallback is a SANCTIONED ADR-013 exemption (owner-granted 2026-08-25)

Lane 3 is what REPAIRS the platform. A builder that only works while the platform is
healthy is useless in the situation it exists for. This carries the same waiver the
cockpit voice does (``ADR-013 voice-survives-crash``): try the dispatcher, fall back to
the local host, never hard-fail because the hub is down. The fallback is the ONLY direct
path in this file and it is never taken while the hub answers.

## ⚠️ ``format=`` (constrained decoding) STAYS ON THE DIRECT PATH

``chat(format=...)`` is how the build planner guarantees a parseable op-list (#380).
``/api/internal/dhq/chat`` has **no ``format`` passthrough**, so routing those calls
through it would silently drop the constraint and return prose where the planner expects
JSON — a parse failure that reads like a model-quality problem and is not. Those calls
stay direct until the endpoint learns ``format``. See ``_should_use_hub``.

## ⚠️ Pinning a model defeats fleet routing

From the endpoint's own docstring: service callers that pin a model "keep their model +
default hub routing". So forwarding ``model`` puts the work straight back on the hub —
the exact problem this change exists to fix. By default we do NOT forward it:
``capability="code"`` routes to Engineering / F.O.R.G.E., which already carries a coding
model, and ``department_dispatcher`` is then free to place the work on whichever node is
healthy. Set ``ARCHIE_ENGINE_PIN_MODEL=1`` to restore pinning if a specific model is
ever required.
"""

from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_HUB_PATH = "/api/internal/dhq/chat"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class InferenceClient:
    """Async inference client. Dispatcher-first, direct-fallback.

    Return shapes are UNCHANGED — callers still read ``response`` and
    ``message.content`` — so no downstream code had to move. A dispatcher-served result
    is tagged ``_via: "hub"``; a fallback is tagged ``_via: "direct"``.
    """

    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        timeout: int = 300,
        hub_url: str | None = None,
        hub_api_key: str | None = None,
        capability: str = "code",
        prefer_agent: str = "F.O.R.G.E.",
        module_id: str = "archie_engine",
    ) -> None:
        self.ollama_host = ollama_host.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.hub_url = (hub_url or os.getenv("ARCHIE_HUB_URL") or "").rstrip("/")
        self.hub_api_key = (
            hub_api_key
            or os.getenv("ARCHIE_HUB_API_KEY")
            or os.getenv("INTERNAL_API_KEY")
            or ""
        )
        self.capability = capability
        self.prefer_agent = prefer_agent
        self.module_id = module_id
        self.pin_model = _env_flag("ARCHIE_ENGINE_PIN_MODEL", False)

    # ---- dispatcher path ------------------------------------------------------

    @property
    def hub_enabled(self) -> bool:
        """Both a URL and a key are required — a half-configured hub is not a hub."""
        return bool(self.hub_url and self.hub_api_key)

    def _should_use_hub(self, format: str | dict | None = None) -> bool:
        """Use the dispatcher unless the call needs something it cannot express."""
        if format:
            return False
        return self.hub_enabled

    async def _hub_complete(
        self, prompt: str, system: str | None, model: str | None
    ) -> str | None:
        """One dispatcher-routed completion. Returns text, or None to fall back.

        NEVER raises — every failure path returns None so the caller falls back rather
        than losing the work.
        """
        payload: dict = {
            "prompt": prompt,
            "capability": self.capability,
            "prefer_agent": self.prefer_agent,
            "module_id": self.module_id,
        }
        if system:
            payload["system_prompt"] = system
        # Opt-in only: pinning forces hub routing and defeats fleet placement.
        if model and self.pin_model:
            payload["model"] = model
        headers = {"Authorization": f"Bearer {self.hub_api_key}"}
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.hub_url}{_HUB_PATH}", json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        # 502 is the endpoint's own "dispatch produced nothing" signal.
                        # Any other status is equally a reason to fall back.
                        logger.info(
                            "[inference] hub returned %s — falling back to direct",
                            resp.status,
                        )
                        return None
                    data = await resp.json()
            if not data.get("success"):
                return None
            return (data.get("response") or "").strip() or None
        except Exception as e:  # noqa: BLE001 - a hub outage must never break Lane 3
            logger.info("[inference] hub unreachable (%s) — falling back to direct", e)
            return None

    @staticmethod
    def _flatten(messages: list[dict]) -> tuple[str, str | None]:
        """Collapse a chat transcript into (prompt, system) for the hub endpoint.

        The endpoint takes a single prompt, not a message list. System turns are lifted
        out and joined; the rest are rendered role-prefixed so multi-turn context
        survives the trip rather than being silently truncated to the last turn.
        """
        systems = [
            (m.get("content") or "").strip()
            for m in messages
            if m.get("role") == "system"
        ]
        turns = [m for m in messages if m.get("role") != "system"]
        if len(turns) == 1:
            body = (turns[0].get("content") or "").strip()
        else:
            body = "\n\n".join(
                f"{(m.get('role') or 'user').upper()}: {(m.get('content') or '').strip()}"
                for m in turns
            )
        system = "\n\n".join(s for s in systems if s) or None
        return body, system

    # ---- public API (shapes unchanged) ----------------------------------------

    async def generate(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
    ) -> dict:
        """Non-streaming text generation. Dispatcher first, direct fallback."""
        if self._should_use_hub():
            text = await self._hub_complete(prompt, system, model)
            if text is not None:
                return {"response": text, "model": model, "done": True, "_via": "hub"}

        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate", json=payload
                ) as resp:
                    data = await resp.json()
                    data.setdefault("_via", "direct")
                    return data
        except Exception as e:
            return {"error": str(e)}

    async def chat(
        self,
        messages: list[dict],
        model: str,
        system: str | None = None,
        format: str | dict | None = None,
    ) -> dict:
        """Non-streaming chat completion. Dispatcher first, direct fallback.

        ``format`` forces structured output (``"json"`` or a JSON schema) via
        constrained decoding — used by the build planner to guarantee a parseable
        op-list (#380). ⚠️ The hub endpoint cannot express it, so a call passing
        ``format`` goes DIRECT and keeps its guarantee.
        """
        if self._should_use_hub(format):
            body, sys_from_msgs = self._flatten(messages)
            text = await self._hub_complete(body, system or sys_from_msgs, model)
            if text is not None:
                return {
                    "message": {"role": "assistant", "content": text},
                    "model": model,
                    "done": True,
                    "_via": "hub",
                }

        payload: dict = {"model": model, "messages": messages, "stream": False}
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/chat", json=payload
                ) as resp:
                    data = await resp.json()
                    data.setdefault("_via", "direct")
                    return data
        except Exception as e:
            return {"error": str(e)}

    # ---- model inventory (always direct — this is not inference) ---------------
    #
    # Listing and warming models is a property of a SPECIFIC host, so these stay on the
    # direct path by design. Reading the tag list is explicitly permitted alongside
    # ADR-013, which governs inference; `department_dispatcher` has no equivalent call.

    async def list_models(self) -> list[dict]:
        """Return the list of models available on the configured host."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    data = await resp.json()
                    return data.get("models", [])
        except Exception:
            return []

    async def is_available(self) -> bool:
        """Return True if the local model host is reachable."""
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{self.ollama_host}/api/tags") as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def warm_model(self, model: str) -> bool:
        """Preload a model into memory on the local host."""
        payload = {"model": model, "prompt": "", "stream": False}
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    f"{self.ollama_host}/api/generate", json=payload
                ) as resp:
                    await resp.json()
                    return True
        except Exception:
            return False
