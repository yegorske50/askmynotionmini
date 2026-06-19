"""Provider factory + cached singletons."""

from __future__ import annotations

import os
from functools import lru_cache

from app.config import settings
from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    NotionSource,
    TranscriptionProvider,
    VideoProvider,
)


def _use_mock() -> bool:
    return os.environ.get("MINIMAX_MOCK_PROVIDERS") == "1" or os.environ.get("TEST_FAST") == "1"


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
    if _use_mock():
        from app.providers.mock_llm import MockLLM

        return MockLLM()
    from app.providers.MiniMax_llm import MiniMaxLLM

    return MiniMaxLLM(
        api_key=settings.MiniMax_api_key or "",
        model=settings.MiniMax_model,
        base_url=settings.MiniMax_base_url,
    )


@lru_cache(maxsize=1)
def get_embedder() -> EmbeddingProvider:
    if _use_mock():
        from app.providers.mock_embed import MockEmbedder

        return MockEmbedder()
    from app.providers.sbert_embed import SBertEmbedder

    return SBertEmbedder(model_name=settings.embed_model)


@lru_cache(maxsize=1)
def get_transcriber() -> TranscriptionProvider:
    if _use_mock():
        from app.providers.mock_transcribe import MockTranscriber

        return MockTranscriber()
    if settings.asr_provider == "local":
        from app.providers.local_transcribe import LocalWhisperTranscriber

        return LocalWhisperTranscriber()
    from app.providers.groq_transcribe import GroqTranscriber

    return GroqTranscriber(api_key=settings.groq_api_key or "")


@lru_cache(maxsize=1)
def get_video() -> VideoProvider:
    if _use_mock():
        from app.providers.mock_video import MockVideoProvider

        return MockVideoProvider()
    from app.providers.ytdlp_video import YtDlpVideoProvider

    return YtDlpVideoProvider()


@lru_cache(maxsize=1)
def get_notion() -> NotionSource:
    if _use_mock() or not settings.notion_token:
        from app.providers.mock_notion import MockNotionSource

        return MockNotionSource()
    from app.providers.notion_source import NotionAPISource

    return NotionAPISource(token=settings.notion_token or "")


def reset_providers() -> None:
    """Used in tests to drop lru_cache singletons."""
    for f in (get_llm, get_embedder, get_transcriber, get_video, get_notion):
        f.cache_clear()
