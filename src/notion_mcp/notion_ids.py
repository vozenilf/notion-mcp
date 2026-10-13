"""Small pure helpers for Notion page IDs and page objects.

Pure = no network, no files, no MCP: data in, data out. That makes them easy to test.
"""

import re
from typing import Any

UNTITLED = "(untitled)"
_ID_AT_END = re.compile(r"[0-9a-f]{32}$")


class InvalidPageIdError(ValueError):
    """Raised when a string doesn't contain a Notion page ID."""


def normalize_page_id(page: str) -> str:
    """Turn a Notion page URL or ID into the standard dashed form.

    Accepts a 32-character ID with or without dashes, or a full page URL
    such as 'https://www.notion.so/My-Page-1a2b...?pvs=4'.
    """

    text = page.strip().split("?")[0].split("#")[0].rstrip("/")
    compact = text.replace("-", "").lower()
    match = _ID_AT_END.search(compact)
    if not match:
        raise InvalidPageIdError(f"No Notion page ID found in {page!r}")
    raw = match.group()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def get_title(page: dict[str, Any]) -> str:
    """Return a page's title as plain text.

    The title lives in page["properties"] under a property whose *type* is "title";
    its name varies ("title", "Name", ...), so we search by type.
    """
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(part["plain_text"] for part in prop["title"]) or UNTITLED
    return UNTITLED


def summarize_page(page: dict[str, Any]) -> dict[str, str]:
    """Keep only the fields Claude needs from Notion's large page object."""
    return {
        "id": page["id"],
        "title": get_title(page),
        "url": page["url"],
        "last_edited": page["last_edited_time"],
    }
