"""The MCP server: exposes a few Notion tools to Claude.

This layer is deliberately thin. Each tool checks its input, calls NotionClient
and turns our errors into messages Claude can act on. All HTTP logic lives in
notion_api.py, all ID parsing in notion_ids.py.
"""

from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.lifespan import lifespan

from notion_mcp.config import load_settings
from notion_mcp.notion_api import NotionClient, NotionError
from notion_mcp.notion_ids import InvalidPageIdError, normalize_page_id

MAX_PAGES_PER_CALL = 10  # keeps one read_pages call from flooding Claude's context

READ_ONLY = {"readOnlyHint": True}


def create_client() -> NotionClient:
    """Build the Notion client from environment settings. Tests replace this function."""
    return NotionClient(load_settings())


@lifespan
async def notion_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Create one NotionClient when the server starts; close it when the server stops."""
    client = create_client()
    try:
        yield {"notion": client}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="notion",
    instructions=(
        "Search, read and write pages in the user's Notion workspace. "
        "Only pages shared with the integration are visible. "
        "Tools accept a page URL or a page ID."
    ),
    lifespan=notion_lifespan,
    mask_error_details=True,
)


def _notion(ctx: Context) -> NotionClient:
    """Return the client created by the lifespan."""
    return ctx.lifespan_context["notion"]


@contextmanager
def _friendly_errors() -> Generator[None]:
    """Turn our own exceptions into ToolError, whose message is always shown to Claude."""
    try:
        yield
    except (NotionError, InvalidPageIdError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
async def search_pages(query: str, ctx: Context) -> list[dict[str, str]]:
    """Search pages by title. Use an empty query to list all pages shared with the integration.

    Returns each page's id, title, url and last edit time.
    """
    with _friendly_errors():
        return await _notion(ctx).search_pages(query)


@mcp.tool(annotations=READ_ONLY)
async def read_page(page: str, ctx: Context) -> dict[str, Any]:
    """Read one page as markdown. `page` is a Notion page URL or ID."""
    with _friendly_errors():
        return await _notion(ctx).read_page(normalize_page_id(page))


@mcp.tool(annotations=READ_ONLY)
async def read_pages(pages: list[str], ctx: Context) -> list[dict[str, Any]]:
    """Read several pages at once (URLs or IDs).

    A page that can't be read gets an entry with an 'error' message instead of failing the call.
    """
    if len(pages) > MAX_PAGES_PER_CALL:
        raise ToolError(f"Read at most {MAX_PAGES_PER_CALL} pages per call.")
    with _friendly_errors():
        page_ids = [normalize_page_id(page) for page in pages]
        return await _notion(ctx).read_pages(page_ids)


@mcp.tool
async def create_page(parent: str, markdown: str, ctx: Context) -> dict[str, str]:
    """Create a new page under `parent` (a page URL or ID).

    Start `markdown` with a '# Heading': it becomes the page title.
    Returns the new page's id and url.
    """
    with _friendly_errors():
        return await _notion(ctx).create_page(normalize_page_id(parent), markdown)


@mcp.tool
async def append_to_page(page: str, markdown: str, ctx: Context) -> dict[str, str]:
    """Add markdown at the end of an existing page (URL or ID). Existing content is kept."""
    with _friendly_errors():
        return await _notion(ctx).append_to_page(normalize_page_id(page), markdown)


def main() -> None:
    """Entry point: serve over stdio, which is how Claude Desktop talks to the server."""
    mcp.run()
