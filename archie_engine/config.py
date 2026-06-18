"""Engine configuration — environment variables and defaults."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class EngineConfig:
    """Engine settings loaded from environment."""

    # Paths
    data_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("ARCHIE_DATA_DIR", str(Path.home() / ".archie"))
    ))

    # Ollama
    ollama_host: str = field(default_factory=lambda: os.environ.get(
        "OLLAMA_HOST", "http://localhost:11434"
    ))
    default_model: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_MODEL", "archie:7b"
    ))

    # Server
    ws_host: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_WS_HOST", "127.0.0.1"
    ))
    ws_port: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_WS_PORT", "9090"
    )))

    # Hub (optional — Plan 3)
    hub_url: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_HUB_URL", ""
    ))
    hub_api_key: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_HUB_API_KEY", ""
    ))
    hub_heartbeat_interval: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_HUB_HEARTBEAT", "30"
    )))
    hub_timeout: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_HUB_TIMEOUT", "10"
    )))
    hub_retry_max: int = 3

    # Dispatch policy — strictly local by default (ADR-003, decision #4): build
    # inference routes through DHQ on the local cluster (PLATFORM target); the
    # engine never escalates to paid cloud. Set ARCHIE_ENGINE_ALLOW_CLOUD=1 to
    # re-enable Claude/cloud escalation later.
    local_only: bool = field(default_factory=lambda: os.environ.get(
        "ARCHIE_ENGINE_ALLOW_CLOUD", ""
    ).lower() not in ("1", "true", "yes"))

    # Build loop (#4256) — externally configurable (env) instead of hard-coded.
    # ADR-003: change set capped at ~25 files; deploy only on a green test run.
    build_max_files: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_ENGINE_MAX_FILES", "25"
    )))
    build_test_command: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_ENGINE_TEST_COMMAND", "python -m pytest -q"
    ))
    build_test_timeout: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_ENGINE_TEST_TIMEOUT", "600"
    )))

    # Platform-target build (#380 engine→platform expansion). The engine clones
    # archie-platform into a SECOND workspace and builds fixes for the platform's
    # Applications/Concepts modules there (PLATFORM_SCOPE). The platform test step is
    # services-free — it just compiles the applied files (no DB/Redis/Ollama); the real
    # gate is F.O.R.G.E. review + Repair Bay QA + the human merge gate.
    platform_workspace: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_PLATFORM_WORKSPACE", "/workspace-platform"
    ))
    platform_repo: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_PLATFORM_REPO", "KytranKatarn/archie-platform"
    ))
    platform_test_command: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_ENGINE_PLATFORM_TEST_COMMAND",
        "git diff --name-only -- '*.py' | xargs -r python -m py_compile",
    ))
    # Autonomous pull-work dedup (#380): skip issues attempted within this window so
    # the scheduler rotates through findings instead of hammering the top one (6h).
    autopull_cooldown_sec: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_AUTOPULL_COOLDOWN_SEC", "21600"
    )))

    # Inbound (hub dispatches work here)
    inbound_host: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_INBOUND_HOST", "0.0.0.0"
    ))
    inbound_port: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_INBOUND_PORT", "9091"
    )))

    # Safety
    shell_denylist: list[str] = field(default_factory=lambda: [
        "rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:",
        "chmod -R 777", "> /dev/sda",
    ])

    @property
    def db_path(self) -> Path:
        return self.data_dir / "engine.db"

    @property
    def hub_skills_cache_dir(self) -> Path:
        return self.data_dir / "skills_cache"

    def ensure_dirs(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
