"""Command router — dispatches intents to tools or inference."""

import logging
import re
import time

from archie_engine.tools import ToolRegistry
from archie_engine.inference import InferenceClient
from archie_engine.personality import PersonalityBuilder
from archie_engine.scope_guard import is_in_scope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation context for platform dispatch (#6729)
# ---------------------------------------------------------------------------
# `user_context` above carries history_LENGTH — a count. For a long time that
# was the ONLY history signal that crossed to the platform, so a delegated
# agent was told "there are 11 earlier messages" and shown none of them.
# Measured on platform task #6727: one turn after answering "Titan", asked
# "Is it bigger than the planet Mercury? ...name it explicitly", the agent
# could not name it and answered "No" — the opposite of the truth. It did not
# ask what "it" meant, because nothing told it a referent existed.
#
# history_length is deliberately KEPT: it is cheap, and it lets the receiver
# distinguish "no history" from "history trimmed to fit".

_CONV_MAX_TURNS = 6
_CONV_MAX_CHARS_PER_TURN = 800
# Dialogue only. system/tool rows are engine bookkeeping and would spend the
# budget without helping a 7B resolve a pronoun.
_CONV_ROLES = ("user", "assistant")


def recent_conversation(history: object, max_turns: int = _CONV_MAX_TURNS) -> list[dict]:
    """The last few dialogue turns as [{"role", "content"}], oldest-first.

    Bounded HERE as well as on the platform: both ends own the 7B fleet's
    context budget, and the receiver cannot un-send an oversized payload.

    Never raises — history is best-effort context, and a malformed row must
    cost the caller nothing more than that row.
    """
    if not isinstance(history, (list, tuple)):
        return []
    out: list[dict] = []
    for row in history:
        if not isinstance(row, dict):
            continue
        role, content = row.get("role"), row.get("content")
        if role not in _CONV_ROLES or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > _CONV_MAX_CHARS_PER_TURN:
            content = content[:_CONV_MAX_CHARS_PER_TURN] + " […truncated]"
        out.append({"role": role, "content": content})
    # Newest turns are what a follow-up refers to; keep those, drop the opening.
    return out[-max_turns:] if max_turns > 0 else out


class CommandRouter:
    def __init__(self, tools: ToolRegistry, inference: InferenceClient,
                 default_model: str = "archie:7b",
                 hub_connector=None,
                 personality_builder: PersonalityBuilder | None = None,
                 scope_config: dict | None = None):
        self.tools = tools
        self.inference = inference
        self.default_model = default_model
        self.hub_connector = hub_connector
        self.personality = personality_builder or PersonalityBuilder()
        # Deny-by-default scope for engine file mutations (ADR-003). None → the
        # DEFAULT_ARCHIE_CODE_SCOPE in scope_guard (archie-code source/tests/docs).
        self.scope_config = scope_config

    async def _enrich_with_kb(self, query: str, limit: int = 3) -> str:
        """Search KB for relevant context when hub is connected. Returns context string or empty."""
        if not self.hub_connector:
            return ""
        try:
            results = await self.hub_connector.search_knowledge(query, limit=limit)
            if not results or not results.get("results"):
                return ""
            snippets = []
            for r in results["results"][:limit]:
                title = r.get("title", "")
                content = r.get("content", "")[:300]
                if title and content:
                    snippets.append(f"- {title}: {content}")
            if not snippets:
                return ""
            return "\n\nRelevant knowledge from the platform:\n" + "\n".join(snippets) + "\n"
        except Exception as e:
            logger.debug("KB enrichment failed (non-critical): %s", e)
            return ""

    async def route(self, intent: dict, context: dict,
                    dispatch_target: str | None = None, capability: str | None = None) -> dict:
        """Route an intent to the appropriate handler. Returns response dict."""
        # Platform dispatch takes priority when specified
        if dispatch_target == "platform" and self.hub_connector:
            return await self._handle_platform_dispatch(
                intent["raw_input"], intent.get("entities", {}), context, capability
            )

        intent_type = intent.get("type", "conversation")
        raw_input = intent.get("raw_input", "")
        entities = intent.get("entities", {})

        handler = {
            "file_operation": self._handle_file_operation,
            "git_operation": self._handle_git_operation,
            "shell_command": self._handle_shell_command,
            "code_task": self._handle_code_task,
            "knowledge_query": self._handle_knowledge_query,
            "conversation": self._handle_conversation,
        }.get(intent_type, self._handle_conversation)

        try:
            return await handler(raw_input, entities, context)
        except Exception as e:
            logger.error("Router error for %s: %s", intent_type, e)
            return {"success": False, "response": f"Error: {e}", "tool_calls": []}

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    async def _handle_file_operation(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Parse operation (read/write/grep/glob) and path, call file_ops tool."""
        # Determine operation
        lower = raw_input.lower()
        if re.search(r"\bgrep\b|\bsearch\b", lower):
            operation = "grep"
        elif re.search(r"\bglob\b|\bfind\b|\blist\b", lower):
            operation = "glob"
        elif re.search(r"\bwrite\b|\bcreate\b|\bsave\b", lower):
            operation = "write"
        else:
            operation = "read"

        # Determine path from entities or raw_input
        files = entities.get("files", [])
        path = files[0] if files else _extract_path(raw_input)

        # FileOpsTool's contract differs per operation (tools/file_ops.py:execute):
        #     read / write / edit -> path=        glob -> pattern=        grep -> pattern= [+ path=]
        # This handler used to pass path= for EVERYTHING, so glob and grep always
        # received pattern='' and were refused ("Unacceptable pattern: ''"). Measured
        # 2026-09-11 against the exact TUI input "list files in the workspace": the
        # engine answered in 0.1s with that refusal — and because _extract_path fell
        # back to the WHOLE SENTENCE as the path, no phrasing of "list files" could
        # ever have succeeded from the TUI. (The six-minute spinner the TUI showed
        # was a separate client bug; see archie-tui/model.go.)
        if operation == "glob":
            # "list files" carries no pattern. The workspace's top level is the honest
            # default; rglob is deliberately NOT the default because FileOpsTool
            # materialises the whole match list and the workspace volumes hold entire
            # repo clones.
            if path and any(ch in path for ch in "*?["):
                pattern = path
            elif path:
                pattern = f"**/{path}"
            else:
                pattern = "*"
            kwargs = {"operation": "glob", "pattern": pattern}
            tool_call = {"tool": "file_ops", "operation": "glob", "pattern": pattern}
        elif operation == "grep":
            pattern = _extract_grep_pattern(raw_input)
            if not pattern:
                return {
                    "success": False,
                    "response": 'grep needs a search term — quote it, e.g. search for "needle" in src/',
                    "tool_calls": [],
                    "model_used": None,
                }
            kwargs = {"operation": "grep", "pattern": pattern, "path": path or None}
            tool_call = {"tool": "file_ops", "operation": "grep", "pattern": pattern, "path": path}
        else:
            if not path:
                # Say so, rather than handing FileOpsTool an empty path and letting it
                # resolve to the workspace root.
                return {
                    "success": False,
                    "response": f"{operation} needs a file path — I could not find one in the request.",
                    "tool_calls": [],
                    "model_used": None,
                }
            kwargs = {"operation": operation, "path": path}
            tool_call = {"tool": "file_ops", "operation": operation, "path": path}

        # Deny-by-default scope guard (ADR-003): the engine may only MUTATE files
        # inside its allowed scope. read/glob/grep stay bounded by the tool's own
        # workspace-escape check; write/edit must additionally pass is_in_scope.
        if operation in ("write", "edit") and not is_in_scope(path, self.scope_config):
            return {
                "success": False,
                "response": (
                    f"Denied by scope guard: '{path}' is outside the engine's "
                    "writable scope (archie-code source/tests/docs only)."
                ),
                "tool_calls": [tool_call],
                "model_used": None,
            }

        result = await self.tools.execute("file_ops", **kwargs)

        return {
            "success": result.success,
            "response": result.output if result.success else result.error,
            "tool_calls": [tool_call],
            "model_used": None,
        }

    async def _handle_git_operation(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Parse git subcommand from raw_input, call git_ops tool."""
        # Extract subcommand — everything after "git "
        match = re.search(r"\bgit\s+(\w+)", raw_input, re.IGNORECASE)
        subcommand = match.group(1) if match else "status"

        tool_call = {"tool": "git_ops", "operation": subcommand}

        result = await self.tools.execute("git_ops", operation=subcommand)

        return {
            "success": result.success,
            "response": result.output if result.success else result.error,
            "tool_calls": [tool_call],
            "model_used": None,
        }

    async def _handle_shell_command(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Extract command after run/execute keyword, call shell_ops tool."""
        match = re.search(r"\b(?:run|execute)\s+(.+)", raw_input, re.IGNORECASE)
        command = match.group(1).strip() if match else raw_input.strip()

        tool_call = {"tool": "shell_ops", "command": command}

        result = await self.tools.execute("shell_ops", command=command)

        return {
            "success": result.success,
            "response": result.output if result.success else result.error,
            "tool_calls": [tool_call],
            "model_used": None,
        }

    # ------------------------------------------------------------------
    # Platform dispatch handler
    # ------------------------------------------------------------------

    async def _handle_platform_dispatch(self, raw_input: str, entities: dict,
                                        context: dict, capability: str | None) -> dict:
        """Dispatch to platform Bridge via hub connector."""
        start = time.monotonic()

        user_context = {
            "working_dir": context.get("working_dir", ""),
            "files": entities.get("files", []),
            "history_length": len(context.get("history", [])),
        }

        resp = await self.hub_connector.dispatch(
            prompt=raw_input,
            agent_target=f"capability:{capability}" if capability else None,
            user_context=user_context,
            conversation=recent_conversation(context.get("history")),
        )

        duration_ms = int((time.monotonic() - start) * 1000)

        if "error" in resp:
            logger.warning("Platform dispatch failed: %s — falling back to local", resp["error"])
            return await self._handle_code_task(raw_input, entities, context)

        agent_name = resp.get("agent_name", "platform agent")
        response_text = resp.get("response", "")
        model_used = resp.get("model", self.default_model)

        # Log the job for activity tracking
        try:
            await self.hub_connector.log_job(
                task=capability or "general",
                agent_name=agent_name,
                result_summary=response_text[:200],
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.warning("Failed to log job: %s", e)

        return {
            "success": True,
            "response": f"[{agent_name}] {response_text}",
            "tool_calls": [],
            "model_used": model_used,
            "agent_name": agent_name,
            "node": resp.get("node", ""),
            # True when `response_text` is the team's actual answer rather than
            # the submit receipt (#6733). The caller records `response` as the
            # assistant turn either way; this says which one it got, so a client
            # can mark an unsettled turn instead of presenting a receipt as a reply.
            "settled": bool(resp.get("settled")),
            "task_id": resp.get("task_id"),
        }

    # ------------------------------------------------------------------
    # Inference handlers
    # ------------------------------------------------------------------

    async def _handle_code_task(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Build system + user prompt, call inference.chat(), return LLM response."""
        kb_context = await self._enrich_with_kb(raw_input)
        system_prompt = (
            self.personality.build_system_prompt() + " "
            "Focus on the code task. Provide a clear, concise solution with working code."
            + kb_context
        )
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=system_prompt,
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }

    async def _handle_knowledge_query(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Answer a knowledge / documentation query via inference."""
        kb_context = await self._enrich_with_kb(raw_input)
        system_prompt = (
            self.personality.build_system_prompt() + " "
            "Answer the question accurately and concisely, citing relevant details."
            + kb_context
        )
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=system_prompt,
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }

    async def _handle_conversation(self, raw_input: str, entities: dict, context: dict) -> dict:
        """General conversation — call inference.chat() with history from context."""
        kb_context = await self._enrich_with_kb(raw_input)
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=self.personality.build_system_prompt() + kb_context,
        )

        content = _extract_content(resp)
        model_used = resp.get("model", self.default_model)

        return {
            "success": "error" not in resp,
            "response": content,
            "tool_calls": [],
            "model_used": model_used,
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _extract_path(text: str) -> str:
    """Best-effort path extraction from a raw input string.

    Returns "" when nothing path-like is present. This used to fall back to
    ``text.strip()`` — the ENTIRE SENTENCE — so "list files in the workspace" was
    handed to the file tool as a path (measured 2026-09-11). The caller decides
    what an absent path means for its operation; this function must not invent one.
    """
    # Match anything that looks like a file path (word chars + . / -)
    match = re.search(r"[\w./\\-]+\.\w+", text)
    return match.group(0) if match else ""


def _extract_grep_pattern(text: str) -> str:
    """The search term for a grep request: a quoted string if there is one,
    else the word after "grep"/"search for"/"search". "" when neither is present —
    FileOpsTool refuses an empty pattern, and the caller turns "" into a clear
    message instead of that refusal."""
    quoted = re.search(r"[\"'`]([^\"'`]+)[\"'`]", text)
    if quoted:
        return quoted.group(1).strip()
    m = re.search(r"\b(?:grep|search(?:\s+for)?)\s+(?:for\s+)?([^\s]+)", text, re.IGNORECASE)
    if m:
        term = m.group(1).strip().strip(",.;:")
        # "search in src/" names a place, not a term.
        if term.lower() not in ("in", "the", "for", "inside", "within"):
            return term
    return ""


def _extract_content(resp: dict) -> str:
    """Pull assistant content from an Ollama chat response dict."""
    if "error" in resp:
        return f"Inference error: {resp['error']}"
    message = resp.get("message", {})
    if isinstance(message, dict):
        return message.get("content", "")
    return str(message)
