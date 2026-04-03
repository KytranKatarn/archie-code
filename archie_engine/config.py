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
