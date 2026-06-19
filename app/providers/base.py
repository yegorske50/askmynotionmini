"""Provider ABCs.

All side-effecting subsystems (LLM, embedding, transcription, video, notion)
are accessed through these interfaces so the rest of the app stays vendor-neutral.
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from dataclasses import dataclass


# ─── LLM ──────────────────────────────────────────────────────────────────────
@dataclass
class ChatMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class ChatChunk:
    delta: str
    finish_reason: str | None = None


class LLMProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> Iterator[ChatChunk]:
        """Yield text deltas; the final chunk has finish_reason set."""

    @abc.abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        """One-shot completion; concatenates deltas."""


# ─── Embeddings ───────────────────────────────────────────────────────────────
class EmbeddingProvider(abc.ABC):
    name: str = "abstract"
    dim: int = 384

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...

    @abc.abstractmethod
    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        ...


# ─── Transcription ────────────────────────────────────────────────────────────
@dataclass
class TranscriptSegment:
    start: float
    end: float
    text_original: str
    text_en: str
    language: str


@dataclass
class TranscriptResult:
    language: str
    segments: list[TranscriptSegment]
    full_text_original: str
    full_text_en: str
    source: str  # "whisper" | "caption" | "manual"


class TranscriptionProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def transcribe(self, audio_path: str, *, language: str | None = None) -> TranscriptResult:
        ...


# ─── Video fetching ───────────────────────────────────────────────────────────
@dataclass
class VideoInfo:
    canonical_url: str
    author: str | None
    local_audio_path: str  # path to a 16kHz mono wav
    duration: float | None


class VideoProvider(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def fetch_audio(self, url: str) -> VideoInfo:
        """Download a public reel and return a 16kHz mono wav. Raises on failure."""


# ─── Notion source ────────────────────────────────────────────────────────────
@dataclass
class NotionBlock:
    block_id: str
    type: str
    text: str
    deep_link: str


@dataclass
class NotionPage:
    page_id: str
    parent_page_id: str | None
    title: str
    url: str
    depth: int
    last_edited_time: str | None
    blocks: list[NotionBlock]
    child_page_ids: list[str]  # for recursion
    status: str  # "ingested" | "skipped" | "error"
    error: str | None = None


class NotionSource(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def get_page(self, page_id: str, depth: int = 0) -> NotionPage:
        ...
