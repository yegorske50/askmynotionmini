"""Mock Notion source — returns a fixed page used by the seeded demo + tests."""

from __future__ import annotations

import re

from app.providers.base import NotionBlock, NotionPage, NotionSource

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


_FIXED_PAGE = NotionPage(
    page_id="mock-page-0001",
    parent_page_id=None,
    title="Demo Notion Page",
    url="https://www.notion.so/demo-page-0001",
    depth=0,
    last_edited_time="2025-01-15T00:00:00.000Z",
    blocks=[
        NotionBlock(
            block_id="blk-001",
            type="heading_1",
            text="Dosa recipe notes",
            deep_link="https://www.notion.so/demo-page-0001#blk001",
        ),
        NotionBlock(
            block_id="blk-002",
            type="paragraph",
            text=(
                "My grandmother's dosa batter uses 2 cups of rice and 1 cup of urad "
                "dal. Soak both separately for 4–6 hours, grind to a thick fluffy "
                "batter, and ferment overnight at room temperature. Salt goes in just "
                "before making dosas."
            ),
            deep_link="https://www.notion.so/demo-page-0001#blk002",
        ),
        NotionBlock(
            block_id="blk-003",
            type="paragraph",
            text=(
                "This page also collects links to great Instagram reels: "
                "https://www.instagram.com/reel/DEMO_EN_1/ "
                "https://www.instagram.com/reel/DEMO_HI_1/ "
                "https://www.instagram.com/reel/DEMO_TE_1/."
            ),
            deep_link="https://www.notion.so/demo-page-0001#blk003",
        ),
    ],
    child_page_ids=[],
    status="ingested",
)


class MockNotionSource(NotionSource):
    name = "mock"

    def get_page(self, page_id: str, depth: int = 0) -> NotionPage:
        return _FIXED_PAGE


def extract_links_from_text(text: str) -> list[str]:
    return _URL_RE.findall(text or "")
