"""Context bridge — structured context sharing between ARCHIE and Claude."""

import json
from datetime import datetime


class ContextBridge:
    def __init__(self, working_dir: str = ""):
        self.working_dir = working_dir

    def build_context(self, task: str, files: list[str] | None = None,
                      intent: dict | None = None, kb_entries: list[dict] | None = None,
                      history: list[dict] | None = None, branch: str | None = None) -> dict:
        return {
            "session_id": None,
            "task": task,
            "working_dir": self.working_dir,
            "files_involved": files or [],
            "intent": intent or {},
            "kb_context": kb_entries or [],
            "history": history or [],
            "branch": branch or "",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def to_markdown(self, ctx: dict) -> str:
        lines = [f"# Task: {ctx['task']}", ""]
        if ctx.get("working_dir"):
            lines.append(f"**Working directory:** `{ctx['working_dir']}`")
        if ctx.get("branch"):
            lines.append(f"**Branch:** `{ctx['branch']}`")
        if ctx.get("files_involved"):
            lines.append(f"**Files:** {', '.join(f'`{f}`' for f in ctx['files_involved'])}")
        if ctx.get("kb_context"):
            lines.append("\n## Knowledge Base Context")
            for entry in ctx["kb_context"]:
                lines.append(f"- {entry.get('content', '')}")
        if ctx.get("history"):
            lines.append("\n## Conversation History")
            for msg in ctx["history"]:
                lines.append(f"**{msg['role']}:** {msg['content']}")
        return "\n".join(lines)

    def to_json(self, ctx: dict) -> str:
        return json.dumps(ctx, indent=2, default=str)
