"""Command router — dispatches intents to tools or inference."""

import logging
import re

from archie_engine.tools import ToolRegistry
from archie_engine.inference import InferenceClient

logger = logging.getLogger(__name__)


class CommandRouter:
    def __init__(self, tools: ToolRegistry, inference: InferenceClient, default_model: str = "qwen2.5:7b"):
        self.tools = tools
        self.inference = inference
        self.default_model = default_model

    async def route(self, intent: dict, context: dict) -> dict:
        """Route an intent to the appropriate handler. Returns response dict."""
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
    # Inference handlers
    # ------------------------------------------------------------------

    async def _handle_code_task(self, raw_input: str, entities: dict, context: dict) -> dict:
        """Build system + user prompt, call inference.chat(), return LLM response."""
        system_prompt = (
            "You are an expert software engineer. "
            "Analyse the code task and provide a clear, concise solution with working code."
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
            "You are a knowledgeable assistant. "
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
