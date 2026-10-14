"""Tests for the MCP layer: a real MCP client talks to our server in memory."""

import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from notion_mcp import server

PAGE_ID = "3f1e2e90-c598-8030-8f11-eba077f3e827"
PAGE_URL = "https://www.notion.so/Meeting-notes-3f1e2e90c59880308f11eba077f3e827?pvs=4"


@pytest.fixture
def connect(monkeypatch, make_client):
    """Return a function that connects an MCP client to our server, backed by a fake Notion."""

    def _connect(handler) -> Client:
        monkeypatch.setattr(server, "create_client", lambda: make_client(handler))
        return Client(server.mcp)

    return _connect


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"Unexpected request to {request.url}")


async def test_server_offers_the_five_tools(connect):
    async with connect(no_network) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == {
        "search_pages",
        "read_page",
        "read_pages",
        "create_page",
        "append_to_page",
    }


async def test_read_page_accepts_a_url(connect):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/pages/{PAGE_ID}/markdown"
        return httpx.Response(200, json={"id": PAGE_ID, "markdown": "# Hello", "truncated": False})

    async with connect(handler) as client:
        result = await client.call_tool("read_page", {"page": PAGE_URL})

    assert result.data == {"id": PAGE_ID, "markdown": "# Hello", "truncated": False}


async def test_create_page_sends_the_normalized_parent(connect):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["parent"] == {"page_id": PAGE_ID}
        return httpx.Response(200, json={"id": PAGE_ID, "url": "https://www.notion.so/new"})

    async with connect(handler) as client:
        result = await client.call_tool("create_page", {"parent": PAGE_URL, "markdown": "# New"})

    assert result.data == {"id": PAGE_ID, "url": "https://www.notion.so/new"}


async def test_notion_errors_reach_claude_as_readable_messages(connect):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"object": "error", "status": 404, "message": "nope"})

    async with connect(handler) as client:
        with pytest.raises(ToolError, match="not shared with the Notion connection"):
            await client.call_tool("read_page", {"page": PAGE_ID})


async def test_invalid_page_id_is_rejected_before_calling_notion(connect):
    async with connect(no_network) as client:
        with pytest.raises(ToolError, match="No Notion page ID found"):
            await client.call_tool("read_page", {"page": "hello"})


async def test_read_pages_limits_the_number_of_pages(connect):
    too_many = [PAGE_ID] * (server.MAX_PAGES_PER_CALL + 1)

    async with connect(no_network) as client:
        with pytest.raises(ToolError, match="at most"):
            await client.call_tool("read_pages", {"pages": too_many})


async def test_unexpected_errors_do_not_leak_details(connect):
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("internal detail: /secret/path")

    async with connect(handler) as client:
        with pytest.raises(ToolError) as caught:
            await client.call_tool("search_pages", {"query": "x"})

    assert "secret" not in str(caught.value)
