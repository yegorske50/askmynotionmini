"""Pydantic schemas for API request/response bodies."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── Workspace ────────────────────────────────────────────────────────────────
class WorkspaceSetIn(BaseModel):
    notion_token: str | None = None
    notion_page_url: str
    name: str = "My Notion"


class WorkspaceOut(BaseModel):
    name: str
    notion_page_id: str
    notion_page_url: str
    mode: Literal["token", "public"]
    counts: dict[str, int] = Field(default_factory=dict)


# ─── Ingest ───────────────────────────────────────────────────────────────────
class IngestOut(BaseModel):
    job_id: int


class IngestStatusOut(BaseModel):
    job_id: int
    status: str
    total_blocks: int
    done_blocks: int
    total_videos: int
    done_videos: int
    indexed_chunks: int
    current_step: str
    error: str | None = None


# ─── Sources ──────────────────────────────────────────────────────────────────
class SourceVideoOut(BaseModel):
    id: int
    source_url: str
    author: str | None = None
    status: str
    error: str | None = None
    language: str | None = None
    has_transcript: bool = False


class SourceNotionPageOut(BaseModel):
    id: int
    notion_page_id: str
    title: str
    url: str
    depth: int
    status: str
    block_count: int = 0


class SourcesOut(BaseModel):
    pages: list[SourceNotionPageOut]
    videos: list[SourceVideoOut]


class TranscriptIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    language: str | None = "en"


# ─── Chat ─────────────────────────────────────────────────────────────────────
class MessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=8_000)
    answer_language: str | None = None  # ISO code, defaults to detected question lang


class CitationOut(BaseModel):
    n: int
    type: Literal["notion_block", "video_transcript", "caption"]
    title: str
    url: str
    deep_link: str
    snippet_original: str
    snippet_en: str | None = None
    language: str | None = None
    start: float | None = None
    end: float | None = None


class MessageOut(BaseModel):
    answer: str
    sources: list[CitationOut]
    message_id: int


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
