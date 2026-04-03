"""Command router — dispatches intents to tools or inference."""

import logging
import re
import time

from archie_engine.tools import ToolRegistry
from archie_engine.inference import InferenceClient

logger = logging.getLogger(__name__)

# Core identity prompt — shared by all LLM handlers
ARCHIE_SYSTEM_PROMPT = (
    "You are A.R.C.H.I.E. (Autonomous Resource & Cognitive Hyperintelligence Engine), "
    "an AI-powered development assistant running locally via the A.R.C.H.I.E. Code CLI. "
    "You have access to tools: file reading/writing, git operations, shell commands, "
    "and a knowledge base with 22,000+ entries. When the user asks about their code or files, "
    "you can read and analyze them. You are part of a platform with 123 AI agents across "
    "16 departments. When connected to the hub, specialist agents handle complex tasks "
    "(code review, security analysis, refactoring). Be helpful, concise, and technically precise."
)


class CommandRouter:
    def __init__(self, tools: ToolRegistry, inference: InferenceClient,
                 default_model: str = "qwen2.5:7b", hub_connector=None):
        self.tools = tools
        self.inference = inference
        self.default_model = default_model
        self.hub_connector = hub_connector

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

        tool_call = {"tool": "file_ops", "operation": operation, "path": path}

        result = await self.tools.execute("file_ops", operation=operation, path=path, working_dir=context.get("working_dir", "."))

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

        tool_call = {"tool": "git_ops", "subcommand": subcommand}

        result = await self.tools.execute(
            "git_ops",
            subcommand=subcommand,
            working_dir=context.get("working_dir", "."),
        )

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

        result = await self.tools.execute(
            "shell_ops",
            command=command,
            working_dir=context.get("working_dir", "."),
        )

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
        }

    # ------------------------------------------------------------------
    # Inference handlers
    # ------------------------------------------------------------------

    async def _handle_code_task(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Build system + user prompt, call inference.chat(), return LLM response."""
        system_prompt = (
            ARCHIE_SYSTEM_PROMPT + " "
            "Focus on the code task. Provide a clear, concise solution with working code."
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
        system_prompt = (
            ARCHIE_SYSTEM_PROMPT + " "
            "Answer the question accurately and concisely, citing relevant details."
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
        history = context.get("history", [])
        messages = list(history) + [{"role": "user", "content": raw_input}]

        resp = await self.inference.chat(
            messages=messages,
            model=self.default_model,
            system=ARCHIE_SYSTEM_PROMPT,
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
    """Best-effort path extraction from a raw input string."""
    # Match anything that looks like a file path (word chars + . / -)
    match = re.search(r"[\w./\\-]+\.\w+", text)
    return match.group(0) if match else text.strip()


def _extract_content(resp: dict) -> str:
    """Pull assistant content from an Ollama chat response dict."""
    if "error" in resp:
        return f"Inference error: {resp['error']}"
    message = resp.get("message", {})
    if isinstance(message, dict):
        return message.get("content", "")
    return str(message)
