"""Tests for NotionClient. No real network: every request goes to a fake handler."""

import json

import httpx
import pytest

from notion_mcp.notion_api import (
    MAX_RETRIES,
    NotionAuthError,
    NotionError,
    NotionNotFoundError,
    NotionPermissionError,
    NotionRateLimitError,
)

PAGE_ID = "3f1e2e90-c598-8030-8f11-eba077f3e827"
OTHER_ID = "3f7e2e90-c598-8043-afec-f414c3eb009a"


def page_object(title: str = "Meeting notes") -> dict:
    return {
        "object": "page",
        "id": PAGE_ID,
        "url": "https://www.notion.so/x",
        "last_edited_time": "2026-10-12T20:00:00.000Z",
        "properties": {"title": {"type": "title", "title": [{"plain_text": title}]}},
    }


def markdown_body(text: str = "# Hello") -> dict:
    return {"object": "page_markdown", "id": PAGE_ID, "markdown": text, "truncated": False}


def error_body(status: int) -> dict:
    return {"object": "error", "status": status, "code": "some_code", "message": "boom"}


async def test_requests_carry_token_and_version(make_client):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"results": []})

    await make_client(handler).search_pages("x")

    assert seen[0].headers["Authorization"] == "Bearer test-token"
    assert seen[0].headers["Notion-Version"] == "2026-03-11"


async def test_search_pages_sends_query_and_returns_summaries(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/search"
        body = json.loads(request.content)
        assert body["query"] == "meeting"
        assert body["filter"] == {"property": "object", "value": "page"}
        return httpx.Response(200, json={"results": [page_object()]})

    results = await make_client(handler).search_pages("meeting")

    assert results == [
        {
            "id": PAGE_ID,
            "title": "Meeting notes",
            "url": "https://www.notion.so/x",
            "last_edited": "2026-10-12T20:00:00.000Z",
        }
    ]


async def test_read_page_returns_markdown(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/pages/{PAGE_ID}/markdown"
        return httpx.Response(200, json=markdown_body("# Hello"))

    page = await make_client(handler).read_page(PAGE_ID)

    assert page == {"id": PAGE_ID, "markdown": "# Hello", "truncated": False}


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, NotionAuthError),
        (403, NotionPermissionError),
        (404, NotionNotFoundError),
        (500, NotionError),
    ],
)
async def test_error_statuses_become_specific_exceptions(make_client, status, error):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=error_body(status))

    with pytest.raises(error):
        await make_client(handler).read_page(PAGE_ID)


async def test_retries_after_429_then_succeeds(make_client):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json=error_body(429))
        return httpx.Response(200, json=markdown_body())

    page = await make_client(handler).read_page(PAGE_ID)

    assert page["markdown"] == "# Hello"
    assert calls == 2


async def test_gives_up_after_too_many_429s(make_client):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json=error_body(429))

    with pytest.raises(NotionRateLimitError):
        await make_client(handler).read_page(PAGE_ID)
    assert calls == MAX_RETRIES + 1


async def test_network_failure_becomes_notion_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no internet", request=request)

    with pytest.raises(NotionError, match="Could not reach Notion"):
        await make_client(handler).search_pages("x")


async def test_read_pages_reports_missing_pages_without_failing_others(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        if OTHER_ID in request.url.path:
            return httpx.Response(404, json=error_body(404))
        return httpx.Response(200, json=markdown_body())

    results = await make_client(handler).read_pages([PAGE_ID, OTHER_ID])

    assert results[0]["markdown"] == "# Hello"
    assert results[1]["id"] == OTHER_ID
    assert "not found" in results[1]["error"].lower()


async def test_create_page_sends_parent_and_markdown(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert json.loads(request.content) == {
            "parent": {"page_id": PAGE_ID},
            "markdown": "# New page",
        }
        return httpx.Response(200, json={"id": OTHER_ID, "url": "https://www.notion.so/new"})

    result = await make_client(handler).create_page(PAGE_ID, "# New page")

    assert result == {"id": OTHER_ID, "url": "https://www.notion.so/new"}


async def test_append_to_page_inserts_at_the_end(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == f"/v1/pages/{PAGE_ID}/markdown"
        assert json.loads(request.content) == {
            "type": "insert_content",
            "insert_content": {"content": "- item", "position": {"type": "end"}},
        }
        return httpx.Response(200, json=markdown_body())

    result = await make_client(handler).append_to_page(PAGE_ID, "- item")

    assert result == {"id": PAGE_ID}
