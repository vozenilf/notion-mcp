"""Shared test helpers. pytest loads this file automatically."""

import httpx
import pytest

from notion_mcp.config import Settings
from notion_mcp.notion_api import NotionClient


@pytest.fixture
def settings() -> Settings:
    """Settings with a fake token: tests never use the real one."""
    return Settings(notion_token="test-token")


@pytest.fixture
def make_client(settings):
    """Build a NotionClient whose requests go to a fake `handler` instead of the internet."""

    def _make(handler) -> NotionClient:
        return NotionClient(settings, transport=httpx.MockTransport(handler))

    return _make
