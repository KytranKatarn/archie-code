"""Hub sync — skill download, agent roster, model state cache."""

import json
import logging
from pathlib import Path
from archie_engine.hub.connector import HubConnector

logger = logging.getLogger(__name__)


class HubSync:
    def __init__(self, connector: HubConnector, cache_dir: Path):
        self.connector = connector
        self.cache_dir = cache_dir
        self._agents: list[dict] = []
        self._models: list[dict] = []

    async def sync_skills(self) -> int:
        """Sync tested skills from hub with incremental timestamps.

        Downloads skills to cache_dir/skills/github/<repo-slug>/<skill>.md,
        confirms successful writes back to hub.
        Returns count of newly synced skills.
        """
        skills_dir = self.cache_dir / "skills" / "github"
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Read last sync token
        token_file = self.cache_dir / ".skill_sync_token"
        since = None
        if token_file.exists():
            since = token_file.read_text().strip() or None

        total_synced = 0

        while True:
            result = await self.connector.sync_skills(
                since=since, limit=50
            )
            if "error" in result:
                logger.warning("Skill sync failed: %s", result["error"])
                break

            skills = result.get("skills", [])
            if not skills:
                break

            # Write files and collect confirmed IDs
            confirmed_ids = []
            for skill in skills:
                repo_slug = skill.get("repo_slug", "unknown")
                skill_slug = skill.get("slug", "unknown")

                repo_dir = skills_dir / repo_slug
                repo_dir.mkdir(parents=True, exist_ok=True)
                file_path = repo_dir / f"{skill_slug}.md"

                try:
                    content = skill.get("content", "")
                    if content:
                        file_path.write_text(content)
                        confirmed_ids.append(skill["skill_id"])
                except OSError as e:
                    logger.warning(
                        "Failed to write skill %s: %s",
                        skill.get("name", "unknown"),
                        e,
                    )

            # Confirm successful installs to hub
            if confirmed_ids:
                node_id = self._get_node_id()
                confirm_result = await self.connector.confirm_skill_sync(
                    skill_ids=confirmed_ids, node_id=node_id
                )
                if "error" in confirm_result:
                    logger.warning(
                        "Skill sync confirm failed: %s",
                        confirm_result["error"],
                    )

            total_synced += len(confirmed_ids)
            since = result.get("sync_token")

            # If fewer than limit, no more pages
            if len(skills) < 50:
                break

        # Save sync token for next run
        if since:
            token_file.write_text(since)

        if total_synced > 0:
            logger.info("Synced %d skills from hub", total_synced)

        return total_synced

    def _get_node_id(self) -> str:
        """Get this node's ID for sync confirmation."""
        import os

        return os.environ.get("ARCHIE_NODE_ID", "hub")

    async def sync_agents(self) -> None:
        """Download agent roster from hub and cache."""
        result = await self.connector.list_agents()
        if "error" in result:
            logger.warning("Agent sync failed: %s", result["error"])
            return

        self._agents = result.get("agents", [])
        agents_file = self.cache_dir / "agents.json"
        agents_file.parent.mkdir(parents=True, exist_ok=True)
        agents_file.write_text(json.dumps(self._agents))
        logger.info("Synced %d agents", len(self._agents))

    async def sync_models(self) -> None:
        """Download model state from hub and cache."""
        result = await self.connector.get_model_state()
        if "error" in result:
            logger.warning("Model sync failed: %s", result["error"])
            return

        self._models = result.get("models", [])
        models_file = self.cache_dir / "models.json"
        models_file.parent.mkdir(parents=True, exist_ok=True)
        models_file.write_text(json.dumps(self._models))
        logger.info("Synced %d models", len(self._models))

    async def sync_all(self) -> None:
        """Run all sync operations."""
        await self.sync_skills()
        await self.sync_agents()
        await self.sync_models()

    def get_cached_skills(self) -> list[dict]:
        """Get cached skills (read from disk, including subdirectories)."""
        skills_dir = self.cache_dir / "skills"
        if not skills_dir.exists():
            return []
        skills = []
        for f in skills_dir.glob("**/*.md"):
            skills.append({"name": f.stem, "content": f.read_text()})
        return skills

    def get_cached_agents(self) -> list[dict]:
        """Get cached agent roster."""
        if self._agents:
            return self._agents
        agents_file = self.cache_dir / "agents.json"
        if agents_file.exists():
            return json.loads(agents_file.read_text())
        return []

    def get_cached_models(self) -> list[dict]:
        """Get cached model state."""
        if self._models:
            return self._models
        models_file = self.cache_dir / "models.json"
        if models_file.exists():
            return json.loads(models_file.read_text())
        return []

    def get_loaded_models(self) -> list[dict]:
        """Get models currently loaded (from cache)."""
        return [m for m in self.get_cached_models() if m.get("loaded")]

    def get_best_agent(self, intent_type: str) -> dict | None:
        """Get best agent for an intent type (simple mapping)."""
        agents = self.get_cached_agents()
        if not agents:
            return None
        # Simple: prefer active agents, default to first one
        active = [a for a in agents if a.get("shift_state") == "active"]
        return active[0] if active else agents[0]
