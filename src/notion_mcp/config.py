"""Settings for the Notion MCP server, read from environment variables.

No other module reads os.environ directly; they all ask this module.
"""

import os
from dataclasses import dataclass, field

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


class ConfigError(Exception):
    """Raised when a required setting is missing."""


@dataclass(frozen=True)
class Settings:
    """Everything the server needs to know to talk to Notion."""

    notion_token: str = field(repr=False)
    notion_version: str = NOTION_VERSION
    api_url: str = NOTION_API_URL


def load_settings() -> Settings:
    """Read settings from the environment, failing early with a clear message."""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "NOTION_TOKEN is not set. Copy .env.example to .env and put your Notion token in it."
        )
    return Settings(notion_token=token)
