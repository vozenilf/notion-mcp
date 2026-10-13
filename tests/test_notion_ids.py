"""Tests for the pure helper functions in notion_ids.py."""

import pytest

from notion_mcp.notion_ids import (
    InvalidPageIdError,
    get_title,
    normalize_page_id,
    summarize_page,
)

PAGE_ID = "3f1e2e90-c598-8030-8f11-eba077f3e827"


@pytest.mark.parametrize(
    "raw",
    [
        "3f1e2e90c59880308f11eba077f3e827",
        "3f1e2e90-c598-8030-8f11-eba077f3e827",
        "https://app.notion.com/p/MCP-Sandbox-3f1e2e90c59880308f11eba077f3e827",
        "https://www.notion.so/MCP-Sandbox-3f1e2e90c59880308f11eba077f3e827?pvs=4",
        "  3F1E2E90C59880308F11EBA077F3E827  ",
    ],
)
def test_normalize_page_id_adds_dashes(raw):
    assert normalize_page_id(raw) == PAGE_ID


@pytest.mark.parametrize("raw", ["", "hello", "https://www.notion.so/no-id-here", "3f1e2e90"])
def test_normalize_page_id_rejects_text_without_id(raw):
    with pytest.raises(InvalidPageIdError):
        normalize_page_id(raw)


def test_normalize_page_id_ignores_hex_letters_in_title():
    url = "https://www.notion.so/Cafe-Bead-3f1e2e90c59880308f11eba077f3e827"
    assert normalize_page_id(url) == PAGE_ID


def make_page(title_parts: list[str], prop_name: str = "title") -> dict:
    """Build a minimal fake Notion page object for tests."""
    return {
        "id": PAGE_ID,
        "url": "https://www.notion.so/x",
        "last_edited_time": "2026-10-12T20:00:00.000Z",
        "properties": {
            prop_name: {"type": "title", "title": [{"plain_text": t} for t in title_parts]}
        },
    }


def test_get_title_joins_rich_text_parts():
    assert get_title(make_page(["Meeting ", "notes"])) == "Meeting notes"


def test_get_title_finds_title_property_by_type_not_name():
    assert get_title(make_page(["Row"], prop_name="Name")) == "Row"


def test_get_title_returns_placeholder_when_empty():
    assert get_title(make_page([])) == "(untitled)"
    assert get_title({"properties": {}}) == "(untitled)"


def test_summarize_page_keeps_only_useful_fields():
    assert summarize_page(make_page(["Shopping list"])) == {
        "id": PAGE_ID,
        "title": "Shopping list",
        "url": "https://www.notion.so/x",
        "last_edited": "2026-10-12T20:00:00.000Z",
    }
