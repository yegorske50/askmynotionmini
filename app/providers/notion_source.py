"""Notion source using the official `notion-client` SDK.

We read text-bearing blocks, capture any URL annotations/bookmarks/embeds, and
surface child_page blocks for recursion (capped by NOTION_MAX_DEPTH).
"""

from __future__ import annotations

import re

from app.providers.base import NotionBlock, NotionPage, NotionSource

_TEXT_TYPES = {
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "quote",
    "callout",
    "to_do",
    "toggle",
    "code",
    "table_row",
    "table",
    "bookmark",
    "embed",
    "image",
    "video",
    "file",
    "pdf",
}

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def _extract_text(block: dict) -> str:
    """Return plain text for any text-bearing Notion block."""
    btype = block.get("type")
    payload = block.get(btype, {}) if btype else {}
    rich = payload.get("rich_text") or []
    parts: list[str] = []
    for r in rich:
        if r.get("type") == "text":
            parts.append(r.get("plain_text", ""))
        elif r.get("type") == "mention":
            parts.append(r.get("plain_text", ""))
        elif r.get("type") == "equation":
            parts.append(r.get("plain_text", ""))
    if not parts and btype in {"bookmark", "embed", "video", "file", "image", "pdf"}:
        url = payload.get("url")
        if url:
            parts.append(url)
    if btype == "table_row":
        # join cells with " | "
        cells = payload.get("cells") or []
        parts = []
        for cell in cells:
            for r in cell:
                if r.get("type") == "text":
                    parts.append(r.get("plain_text", ""))
        return " | ".join(parts)
    return "".join(parts).strip()


def _collect_links_from_block(block: dict) -> list[str]:
    """All URLs reachable from a single Notion block (rich_text + payload.url)."""
    btype = block.get("type")
    payload = block.get(btype, {}) if btype else {}
    urls: list[str] = []
    for r in payload.get("rich_text") or []:
        if r.get("href"):
            urls.append(r["href"])
    if payload.get("url"):
        urls.append(payload["url"])
    if btype == "bookmark" and payload.get("url"):
        urls.append(payload["url"])
    # fallback: any URL in plain text
    txt = _extract_text(block)
    urls.extend(_URL_RE.findall(txt))
    # de-dup, preserve order
    seen = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _block_deep_link(page_url: str, block_id: str) -> str:
    base = page_url.split("?")[0].split("#")[0]
    short = block_id.replace("-", "")
    return f"{base}#{short}"


class NotionAPISource(NotionSource):
    name = "notion-api"

    def __init__(self, token: str):
        self.token = token
        self._client = None

    def _get_client(self):
        if self._client is None:
            from notion_client import Client

            self._client = Client(auth=self.token)
        return self._client

    def get_page(self, page_id: str, depth: int = 0) -> NotionPage:
        from notion_client.errors import APIResponseError

        client = self._get_client()
        try:
            page = client.pages.retrieve(page_id=page_id)
        except APIResponseError as e:
            return NotionPage(
                page_id=page_id,
                parent_page_id=None,
                title="(unavailable)",
                url="",
                depth=depth,
                last_edited_time=None,
                blocks=[],
                child_page_ids=[],
                status="skipped",
                error=f"notion error: {e.code}",
            )

        # Title
        props = page.get("properties", {})
        title = ""
        for prop in props.values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop.get("title", []))
                break
        if not title:
            title = "(untitled)"

        url = page.get("url", "")
        last_edited = page.get("last_edited_time")

        # Walk child blocks
        blocks: list[NotionBlock] = []
        child_pages: list[str] = []
        cursor = None
        while True:
            params = {"block_id": page_id, "page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            try:
                resp = client.blocks.children.list(**params)
            except APIResponseError as e:
                return NotionPage(
                    page_id=page_id,
                    parent_page_id=None,
                    title=title,
                    url=url,
                    depth=depth,
                    last_edited_time=last_edited,
                    blocks=blocks,
                    child_page_ids=[],
                    status="error",
                    error=f"blocks.list failed: {e.code}",
                )
            for b in resp.get("results", []):
                btype = b.get("type")
                if btype == "child_page":
                    cp_id = b.get("id")
                    if cp_id:
                        child_pages.append(cp_id)
                    continue
                if btype in _TEXT_TYPES:
                    text = _extract_text(b)
                    if not text:
                        continue
                    blocks.append(
                        NotionBlock(
                            block_id=b["id"],
                            type=btype,
                            text=text,
                            deep_link=_block_deep_link(url, b["id"]),
                        )
                    )
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")

        return NotionPage(
            page_id=page_id,
            parent_page_id=None,
            title=title,
            url=url,
            depth=depth,
            last_edited_time=last_edited,
            blocks=blocks,
            child_page_ids=child_pages,
            status="ingested",
        )
