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
    # Planner reliability (#380 Phase 1): on a plan that won't parse OR fails dry-run
    # validation (out-of-scope path / an edit whose old_string isn't in the file), the
    # build loop re-prompts the model with the specific error this many times before
    # failing. Model-independent — raises yield without changing the model.
    build_plan_max_retries: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_BUILD_PLAN_MAX_RETRIES", "2"
    )))
    # Max chars of the target file's current content injected into the plan prompt so the
    # model copies the exact edit old_string instead of guessing (#380 Phase 2b). Files
    # over budget are windowed around the flagged line.
    build_plan_file_budget: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_BUILD_PLAN_FILE_BUDGET", "16000"
    )))
    # Model for the PLAN (coordinate) step. The eval (#380 Phase 2) showed a coding
    # model writes far better file-op plans than the general default once it can see the
    # file: qwen2.5-coder:7b ~60-75% plan-ok vs qwen2.5:7b ~25%. Sent as model_override
    # so the dispatcher pins it on hub Ollama (which has it) under F.O.R.G.E.'s accounting.
    build_plan_model: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_BUILD_PLAN_MODEL", "qwen2.5-coder:7b"
    ))

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
    # Per-build worktree isolation (#4253). Each build runs in a throwaway git worktree
    # carved off fresh origin/<base>, so repeated/concurrent runs never mutate — or read
    # a dirty — shared checkout (the 0%-success root cause: branching off the prior failed
    # run's dirty HEAD). Lives on the writable /data volume (rootfs is read-only; the
    # /workspace[-platform] mounts hold the base checkouts and must not host worktrees).
    worktree_root: str = field(default_factory=lambda: os.environ.get(
        "ARCHIE_ENGINE_WORKTREE_ROOT", "/data/engine-worktrees"
    ))
    # Autonomous pull-work dedup (#380): skip issues attempted within this window so
    # the scheduler rotates through findings instead of hammering the top one (6h).
    autopull_cooldown_sec: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_AUTOPULL_COOLDOWN_SEC", "21600"
    )))
    # How many open issues to fetch per autopull cycle. The Repair Bay queue is
    # dominated by out-of-scope / core-platform findings at the top, so in-scope
    # (Applications/Concepts) findings can rank well down the list — the fetch window
    # MUST be wide enough to reach them or every cycle no-ops. Tunable via env.
    autopull_fetch_limit: int = field(default_factory=lambda: int(os.environ.get(
        "ARCHIE_AUTOPULL_FETCH_LIMIT", "200"
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
