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
from archie_engine.dispatch_strategy import DispatchStrategy, DispatchTarget, DispatchDecision
from archie_engine.state_sync import StateSyncChannel, SyncEvent
from archie_engine.learning import LearningStore
from archie_engine.claude.escalation import EscalationDetector
from archie_engine.claude.mcp_server import MCPToolServer
from archie_engine.personality import PersonalityBuilder
from archie_engine.hub.inbound import InboundServer

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: EngineConfig, custom_skill_dirs: list[Path] | None = None):
        self.config = config
        self.db = Database(config.db_path)
        self.sessions = SessionManager(self.db)
        self.inference = InferenceClient(config.ollama_host)
        self.intent_parser = IntentParser()
        self.tools = self._build_tool_registry()
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

        # Hub connectivity (optional) — must be set up BEFORE router so hub_connector is available
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

        # Inbound server (hub dispatches work here)
        self.inbound_server: InboundServer | None = None

        # Personality
        self.personality = PersonalityBuilder()

        # Router — created after hub_connector so it can be wired in
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
            hub_connector=self.hub_connector,
            personality_builder=self.personality,
        )

        # Dispatch strategy
        self.dispatch_strategy = DispatchStrategy(
            hub_available=is_hub_configured(config)
        )

        # State sync for Claude collaboration
        self.state_sync = StateSyncChannel()

        # Learning store for escalation patterns
        self.learning_store = LearningStore(data_dir=config.data_dir)

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
            self.dispatch_strategy.hub_available = (self.hub_heartbeat.status == HubStatus.CONNECTED)
            if self.hub_sync and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self.hub_sync.sync_all()
            if self.hub_connector and self.hub_heartbeat and self.hub_heartbeat.status == HubStatus.CONNECTED:
                await self._fetch_personality()

                # Start inbound server for accepting hub-dispatched work
                node_key = self.hub_connector.auth.load_node_key()
                if node_key:
                    self.inbound_server = InboundServer(
                        host=self.config.inbound_host,
                        port=self.config.inbound_port,
                        node_api_key=node_key,
                    )
                    self.inbound_server.set_job_handler(self.handle_inbound_job)
                    await self.inbound_server.start()
        self.skill_registry.load()
        logger.info("ARCHIE Engine started")

    async def stop(self) -> None:
        if self.inbound_server:
            await self.inbound_server.stop()
        if self.hub_heartbeat:
            await self.hub_heartbeat.stop()
        await self.server.stop()
        await self.db.close()
        logger.info("ARCHIE Engine stopped")

    async def _fetch_personality(self) -> None:
        """Fetch personality data from hub and update the builder."""
        try:
            data = await self.hub_connector.get_personality(agent_id=2)  # ARCHIE is agent_id=2
            if "error" not in data:
                self.personality.update_from_hub(data)
                logger.info("Personality loaded: mood=%s", data.get("mood", {}).get("current", "unknown"))
            else:
                logger.warning("Could not fetch personality: %s", data.get("error"))
        except Exception as e:
            logger.warning("Personality fetch failed: %s — using baseline", e)

    async def handle_message(self, msg: dict) -> dict:
        """Process a message from WebSocket client."""
        msg_type = msg.get("type", "")

        if msg_type == "hub_status":
            return {
                "type": "hub_status",
                "hub_status": self.hub_status.value,
                "node_id": self.hub_heartbeat.node_id if self.hub_heartbeat else None,
            }

        if msg_type == "platform_status":
            return await self._get_platform_status()

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

        if msg_type == "delegate":
            return await self._handle_delegation(msg)

        if msg_type == "state_sync":
            return self._handle_incoming_sync(msg)

        return {"type": "error", "error": f"Unknown message type: {msg_type}"}

    async def _get_platform_status(self) -> dict:
        """Gather platform status data for the TUI status panel."""
        status = {
            "type": "platform_status",
            "hub": self.hub_status.value,
            "model": self.config.default_model,
        }

        if not self.hub_connector or self.hub_status.value != "connected":
            status["agents"] = None
            status["models"] = None
            status["health"] = None
            return status

        # Fetch data in parallel where possible
        try:
            agents_data = await self.hub_connector.list_agents()
            if "error" not in agents_data:
                agents = agents_data.get("agents", [])
                active = sum(1 for a in agents if a.get("shift_state") == "active")
                total = len(agents)
                status["agents"] = {"active": active, "total": total}
            else:
                status["agents"] = None
        except Exception:
            status["agents"] = None

        try:
            models_data = await self.hub_connector.get_model_state()
            if "error" not in models_data:
                status["models"] = models_data.get("models", [])
            else:
                status["models"] = None
        except Exception:
            status["models"] = None

        try:
            health_data = await self.hub_connector.health_check()
            if "error" not in health_data:
                status["health"] = health_data
            else:
                status["health"] = None
        except Exception:
            status["health"] = None

        return status

    async def handle_inbound_job(self, job: dict) -> dict:
        """Process a job dispatched from the hub.

        Called by InboundServer when the hub sends work to this node.
        Routes through the engine's intent parser and router.
        """
        task = job.get("task", "")
        context = job.get("context", {})

        try:
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]
            await self.sessions.add_message(session_id, "user", f"[hub-dispatch] {task}")

            intent = self.intent_parser.classify(task)
            decision = self.dispatch_strategy.decide(intent)

            # For inbound hub work, always process locally (don't re-dispatch to hub)
            build_ctx = await self.sessions.build_context(session_id)
            build_ctx.update(context)
            result = await self.router.route(intent, build_ctx)

            response = result.get("response", "")
            await self.sessions.add_message(session_id, "assistant", response)

            # Log job completion back to hub
            if self.hub_connector:
                await self.hub_connector.log_job(
                    task=task,
                    agent_name="ARCHIE Code Engine",
                    result_summary=response[:200],
                    duration_ms=0,
                )

            return {
                "success": True,
                "response": response,
                "intent": intent["type"],
                "session_id": session_id,
            }
        except Exception as e:
            logger.error("Inbound job failed: %s", e)
            return {"success": False, "error": str(e)}

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

        # Decide dispatch target
        decision = self.dispatch_strategy.decide(intent)
        logger.info("Dispatch: %s → %s (%s)", intent["type"], decision.target.value, decision.reason)

        # Check learning store before platform dispatch
        if decision.target == DispatchTarget.PLATFORM:
            learned = self.learning_store.find_match(
                intent_type=intent["type"], task_summary=content
            )
            if learned:
                logger.info("Found learned pattern — handling locally instead of escalating")
                decision = DispatchDecision(
                    target=DispatchTarget.LOCAL,
                    reason=f"Learned pattern: {learned['resolution'][:50]}",
                    capability=decision.capability,
                )

        # Build context
        context = await self.sessions.build_context(session_id)

        # Route to handler
        result = await self.router.route(
            intent, context,
            dispatch_target=decision.target.value if decision.target != DispatchTarget.LOCAL else None,
            capability=decision.capability,
        )

        # Record assistant response
        response_text = result.get("response", "")
        await self.sessions.add_message(session_id, "assistant", response_text)

        return {
            "type": "response",
            "session_id": session_id,
            "content": response_text,
            "intent": intent["type"],
            "dispatch_target": decision.target.value,
            "tool_calls": result.get("tool_calls", []),
        }

    async def _handle_delegation(self, msg: dict) -> dict:
        """Handle a task delegated from Claude."""
        task = msg.get("task", "")
        files = msg.get("files", [])
        session_id = msg.get("session_id")

        if not session_id:
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]

        self.state_sync.emit(SyncEvent(
            kind="task_started",
            data={"task": task, "source": "claude_delegation", "files": files},
        ))

        intent = self.intent_parser.classify(task)
        decision = self.dispatch_strategy.decide(intent)
        context = await self.sessions.build_context(session_id)
        context["files_involved"] = files

        result = await self.router.route(
            intent, context,
            dispatch_target=decision.target.value if decision.target != DispatchTarget.LOCAL else None,
            capability=decision.capability,
        )

        self.state_sync.emit(SyncEvent(
            kind="task_completed",
            data={"task": task, "success": result.get("success", False)},
        ))

        return {
            "type": "delegation_result",
            "session_id": session_id,
            "task": task,
            "success": result.get("success", False),
            "content": result.get("response", ""),
            "intent": intent["type"],
        }

    def _handle_incoming_sync(self, msg: dict) -> dict:
        """Handle a state sync event from Claude."""
        event_data = msg.get("event", {})
        event = SyncEvent(
            kind=event_data.get("kind", "unknown"),
            data=event_data.get("data", {}),
        )

        conflicts = self.state_sync.check_conflicts(event)
        if conflicts:
            logger.warning("State sync conflicts: %s", conflicts)

        self.state_sync.emit(event)

        return {
            "type": "sync_ack",
            "conflicts": conflicts,
        }
