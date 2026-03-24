"""ARCHIE Engine — main daemon wiring all components."""

import logging
from pathlib import Path

from archie_engine.config import EngineConfig
from archie_engine.database import Database
from archie_engine.session import SessionManager
from archie_engine.inference import InferenceClient
from archie_engine.intent import IntentParser
from archie_engine.router import CommandRouter
from archie_engine.server import EngineServer
from archie_engine.tools import ToolRegistry
from archie_engine.tools.file_ops import FileOpsTool
from archie_engine.tools.git_ops import GitOpsTool
from archie_engine.tools.shell_ops import ShellOpsTool
from archie_engine.hub import HubStatus, is_hub_configured
from archie_engine.hub.auth import HubAuth
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.heartbeat import Heartbeat
from archie_engine.hub.sync import HubSync
from archie_engine.skills import SkillRegistry
from archie_engine.skills.executor import SkillExecutor
from archie_engine.claude.context_bridge import ContextBridge
from archie_engine.claude.escalation import EscalationDetector
from archie_engine.claude.mcp_server import MCPToolServer

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: EngineConfig, custom_skill_dirs: list[Path] | None = None):
        self.config = config
        self.db = Database(config.db_path)
        self.sessions = SessionManager(self.db)
        self.inference = InferenceClient(config.ollama_host)
        self.intent_parser = IntentParser()
        self.tools = self._build_tool_registry()
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
        )
        self.server = EngineServer(config.ws_host, config.ws_port)

        # Skills
        skill_executor = SkillExecutor(
            inference=self.inference, tools=self.tools, default_model=config.default_model
        )
        skill_dirs = [
            Path(__file__).parent / "skills" / "community",  # Built-in community skills
        ]
        if config.hub_skills_cache_dir.exists():
            skill_dirs.append(config.hub_skills_cache_dir / "skills")  # Hub-synced skills
        if custom_skill_dirs:
            skill_dirs.extend(custom_skill_dirs)  # User custom skills
        self.skill_registry = SkillRegistry(skill_dirs=skill_dirs, executor=skill_executor)

        # Claude collaboration
        self.context_bridge = ContextBridge(working_dir=str(Path.cwd()))
        self.escalation_detector = EscalationDetector()
        self.mcp_server = MCPToolServer(tools=[
            {"name": "file_read", "description": "Read a file", "parameters": {"path": {"type": "string"}}},
            {"name": "file_write", "description": "Write a file", "parameters": {"path": {"type": "string"}, "content": {"type": "string"}}},
            {"name": "git_status", "description": "Git repository status", "parameters": {}},
            {"name": "git_diff", "description": "Git diff of changes", "parameters": {}},
            {"name": "shell_exec", "description": "Execute shell command", "parameters": {"command": {"type": "string"}}},
            {"name": "search_knowledge", "description": "Search ARCHIE knowledge base", "parameters": {"query": {"type": "string"}}},
        ])

        # Hub connectivity (optional)
        self.hub_connector: HubConnector | None = None
        self.hub_heartbeat: Heartbeat | None = None
        self.hub_sync: HubSync | None = None
        self._hub_status = HubStatus.DISCONNECTED

        if is_hub_configured(config):
            auth = HubAuth(key_file=config.data_dir / ".hub_key")
            if config.hub_api_key and not auth.has_key():
                auth.store_key(config.hub_api_key)
            self.hub_connector = HubConnector(
                hub_url=config.hub_url, auth=auth, timeout=config.hub_timeout
            )
            self.hub_heartbeat = Heartbeat(
                connector=self.hub_connector, interval=config.hub_heartbeat_interval
            )
            self.hub_sync = HubSync(
                connector=self.hub_connector, cache_dir=config.hub_skills_cache_dir
            )

    @property
    def hub_status(self) -> HubStatus:
        if self.hub_heartbeat:
            return self.hub_heartbeat.status
        return HubStatus.DISCONNECTED

    @property
    def is_running(self) -> bool:
        return self.server.is_running

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        workspace = Path.cwd()
        registry.register(FileOpsTool(workspace=workspace))
        registry.register(GitOpsTool(workspace=workspace))
        registry.register(ShellOpsTool(workspace=workspace, config=self.config))
        return registry

    async def start(self) -> None:
        self.config.ensure_dirs()
        await self.db.initialize()
        self.server.set_handler(self.handle_message)
        await self.server.start()
        if self.hub_heartbeat:
            await self.hub_heartbeat.start()
            if self.hub_sync and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self.hub_sync.sync_all()
        self.skill_registry.load()
        logger.info("ARCHIE Engine started")

    async def stop(self) -> None:
        if self.hub_heartbeat:
            await self.hub_heartbeat.stop()
        await self.server.stop()
        await self.db.close()
        logger.info("ARCHIE Engine stopped")

    async def handle_message(self, msg: dict) -> dict:
        """Process a message from WebSocket client."""
        msg_type = msg.get("type", "")

        if msg_type == "hub_status":
            return {
                "type": "hub_status",
                "hub_status": self.hub_status.value,
                "node_id": self.hub_heartbeat.node_id if self.hub_heartbeat else None,
            }

        if msg_type == "session_create":
            working_dir = msg.get("working_dir", str(Path.cwd()))
            session = await self.sessions.create(working_dir=working_dir)
            return {"type": "session_created", "session_id": session["id"]}

        if msg_type == "session_resume":
            session_id = msg.get("session_id", "")
            session = await self.sessions.get(session_id)
            if session:
                return {"type": "session_resumed", "session_id": session["id"]}
            return {"type": "error", "error": f"Session not found: {session_id}"}

        if msg_type == "list_skills":
            return {
                "type": "skills_list",
                "skills": self.skill_registry.list_skills(),
            }

        if msg_type == "message":
            return await self._process_chat_message(msg)

        return {"type": "error", "error": f"Unknown message type: {msg_type}"}

    async def _process_chat_message(self, msg: dict) -> dict:
        content = msg.get("content", "")
        session_id = msg.get("session_id")

        # Create session if needed
        if not session_id:
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]

        # Record user message
        await self.sessions.add_message(session_id, "user", content)

        # Check for slash command
        if content.startswith("/"):
            name, raw_args = self.skill_registry.parse_command(content)
            skill = self.skill_registry.get(name)
            if skill:
                args = {}
                if raw_args:
                    args["input"] = raw_args
                context = await self.sessions.build_context(session_id)
                result = await self.skill_registry.execute(name, args=args, context=context)
                response_text = result.get("response", "")
                await self.sessions.add_message(session_id, "assistant", response_text)
                return {
                    "type": "response",
                    "session_id": session_id,
                    "content": response_text,
                    "intent": f"skill:{name}",
                    "tool_calls": result.get("tool_calls", []),
                }

        # Classify intent
        intent = self.intent_parser.classify(content)

        # Build context
        context = await self.sessions.build_context(session_id)

        # Route to handler
        result = await self.router.route(intent, context)

        # Record assistant response
        response_text = result.get("response", "")
        await self.sessions.add_message(session_id, "assistant", response_text)

        return {
            "type": "response",
            "session_id": session_id,
            "content": response_text,
            "intent": intent["type"],
            "tool_calls": result.get("tool_calls", []),
        }
