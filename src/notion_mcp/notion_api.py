"""Async client for the few Notion API endpoints this server needs.

This module knows nothing about MCP. It turns Python calls into HTTP requests
and turns Notion's error responses into clear Python exceptions.
"""

import asyncio
from typing import Any

import httpx

from notion_mcp.config import Settings
from notion_mcp.notion_ids import summarize_page

MAX_CONCURRENT_REQUESTS = 3  # Notion allows about 3 requests per second on average
MAX_RETRIES = 3  # extra attempts after a 429 "rate limited" answer
DEFAULT_RETRY_DELAY = 1.0  # seconds, used when Notion doesn't say how long to wait


class NotionError(Exception):
    """Base class for every error this client raises."""


class NotionAuthError(NotionError):
    """The token is wrong or revoked (HTTP 401)."""


class NotionPermissionError(NotionError):
    """The connection lacks a capability, e.g. 'Insert content' (HTTP 403)."""


class NotionNotFoundError(NotionError):
    """The page doesn't exist or isn't shared with the connection (HTTP 404)."""


class NotionRateLimitError(NotionError):
    """Notion kept answering 429 even after retrying."""


class NotionClient:
    """Talks to the Notion API. Create one per server and reuse it."""

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=settings.api_url,
            headers={
                "Authorization": f"Bearer {settings.notion_token}",
                "Notion-Version": settings.notion_version,
            },
            timeout=30.0,
            transport=transport,
        )
        self._limit = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def aclose(self) -> None:
        """Close the underlying HTTP connections."""
        await self._http.aclose()

    async def search_pages(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Find pages whose title matches `query` (an empty query lists all shared pages)."""
        data = await self._request(
            "POST",
            "/search",
            json={
                "query": query,
                "filter": {"property": "object", "value": "page"},
                "page_size": limit,
            },
        )
        return [summarize_page(page) for page in data["results"]]

    async def read_page(self, page_id: str) -> dict[str, Any]:
        """Return one page's content as markdown."""
        data = await self._request("GET", f"/pages/{page_id}/markdown")
        return {"id": data["id"], "markdown": data["markdown"], "truncated": data["truncated"]}

    async def read_pages(self, page_ids: list[str]) -> list[dict[str, Any]]:
        """Read several pages concurrently. A page that fails doesn't stop the others."""
        results = await asyncio.gather(
            *(self.read_page(page_id) for page_id in page_ids), return_exceptions=True
        )
        pages = []
        for page_id, result in zip(page_ids, results, strict=True):
            if isinstance(result, NotionError):
                pages.append({"id": page_id, "error": str(result)})
            elif isinstance(result, BaseException):
                raise result
            else:
                pages.append(result)
        return pages

    async def create_page(self, parent_id: str, markdown: str) -> dict[str, str]:
        """Create a page under `parent_id`. The first '# heading' becomes the title."""
        data = await self._request(
            "POST", "/pages", json={"parent": {"page_id": parent_id}, "markdown": markdown}
        )
        return {"id": data["id"], "url": data["url"]}

    async def append_to_page(self, page_id: str, markdown: str) -> dict[str, str]:
        """Add markdown at the end of an existing page."""
        data = await self._request(
            "PATCH",
            f"/pages/{page_id}/markdown",
            json={
                "type": "insert_content",
                "insert_content": {"content": markdown, "position": {"type": "end"}},
            },
        )
        return {"id": data["id"]}

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send one request (retrying on HTTP 429) and return the JSON body."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self._limit:
                    response = await self._http.request(method, path, json=json)
            except httpx.HTTPError as exc:
                raise NotionError(f"Could not reach Notion: {exc}") from exc

            if response.status_code != 429:
                return _parse(response)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(_retry_delay(response))
        raise NotionRateLimitError("Notion is rate limiting requests; try again in a minute.")


def _parse(response: httpx.Response) -> dict[str, Any]:
    """Return the JSON body of a successful response, or raise a matching NotionError."""
    if response.is_success:
        return response.json()
    message = _error_message(response)
    if response.status_code == 401:
        raise NotionAuthError(f"Notion rejected the token: {message}")
    if response.status_code == 403:
        raise NotionPermissionError(f"The connection is missing a capability: {message}")
    if response.status_code == 404:
        raise NotionNotFoundError("Page not found, or not shared with the Notion connection.")
    raise NotionError(f"Notion API error {response.status_code}: {message}")


def _error_message(response: httpx.Response) -> str:
    """Notion's own error message if the body is JSON, otherwise the raw text."""
    try:
        return response.json().get("message", response.text)
    except ValueError:
        return response.text


def _retry_delay(response: httpx.Response) -> float:
    """How long Notion asks us to wait (Retry-After header), or a default."""
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return DEFAULT_RETRY_DELAY
