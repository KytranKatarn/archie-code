"""Hub authentication — API key storage and Bearer token construction."""

import os
import stat
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class HubAuth:
    """Manages API key storage and auth headers for hub communication."""

    def __init__(self, key_file: Path):
        self.key_file = key_file

    def store_key(self, key: str) -> None:
        """Store API key to file with restricted permissions."""
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.key_file.write_text(key)
        try:
            os.chmod(self.key_file, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass  # Windows doesn't support chmod

    def load_key(self) -> str | None:
        """Load API key from file. Returns None if not found."""
        if not self.key_file.exists():
            return None
        return self.key_file.read_text().strip()

    def clear_key(self) -> None:
        """Delete stored API key."""
        if self.key_file.exists():
            self.key_file.unlink()

    def has_key(self) -> bool:
        """Check if an API key is stored."""
        return self.key_file.exists()

    def get_headers(self) -> dict:
        """Get auth headers for HTTP requests."""
        key = self.load_key()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers
