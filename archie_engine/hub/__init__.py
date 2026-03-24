"""Hub connectivity — connects engine to ARCHIE platform."""

from enum import Enum


class HubStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    OFFLINE = "offline"
    AUTH_FAILED = "auth_failed"


def is_hub_configured(config) -> bool:
    """Check if hub URL and API key are set."""
    return bool(config.hub_url and config.hub_api_key)
