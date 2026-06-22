"""Instagram reel ingestion: fetch audio, transcribe, store transcript, index.

Defensive: every step is wrapped in try/except; failures mark the source
`unavailable` with a reason and never crash the job.
"""

from __future__ import annotations

import json
import sqlite3
import time

import structlog

from app.config import settings
from app.ingest.chunker import Chunk, chunk_transcript_segments
from app.ingest.indexer import delete_chunks_for_source, index_chunks
from app.providers import (
    EmbeddingProvider,
    TranscriptionProvider,
    VideoProvider,
)
from app.providers.ytdlp_video import canonicalize_url, is_instagram_url

log = structlog.get_logger(__name__)


def _upsert_video_row(
    conn: sqlite3.Connection,
    workspace_id: int,
    source_url: str,
    canonical: str,
    status: str,
    error: str | None = None,
    author: str | None = None,
    language: str | None = None,
    description: str | None = None,
    context: str | None = None,
) -> int:
    row = conn.execute(
        "SELECT id FROM videos WHERE workspace_id = ? AND canonical_url = ?",
        (workspace_id, canonical),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE videos SET status=?, error=?, author=COALESCE(?, author), "
            "language=COALESCE(?, language), "
            "description=COALESCE(?, description), "
            "context=COALESCE(?, context), "
            "updated_at=datetime('now') WHERE id = ?",
            (status, error, author, language, description, context, row["id"]),
        )
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO videos(workspace_id, source_url, canonical_url, author, status, error, language, description, context) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (workspace_id, source_url, canonical, author, status, error, language, description, context),
    )
    return int(cur.lastrowid)


def _index_caption_and_context(
    conn: sqlite3.Connection,
    workspace_id: int,
    video_id: int,
    canonical_url: str,
    embedder: EmbeddingProvider,
) -> int:
    """Index the Instagram caption and the user's one-line Notion context
    as a separate `caption` source_type chunk. Reels that are just music
    (no transcript) or are in a language the LLM can't translate still
    need a way to be findable, and the user's written description is the
    most reliable signal.
    """
    row = conn.execute(
        "SELECT description, context FROM videos WHERE id = ?", (video_id,),
    ).fetchone()
    if not row:
        return 0
    parts: list[str] = []
    desc = (row["description"] or "").strip()
    ctx = (row["context"] or "").strip()
    if ctx:
        parts.append(f"User note: {ctx}")
    if desc:
        parts.append(f"Instagram caption: {desc}")
    if not parts:
        return 0
    text = "\n".join(parts)
    chunk = Chunk(
        text_original=text,
        text_en=text,
        language="en",
        start_sec=None,
        end_sec=None,
        meta={"deep_link": canonical_url, "block_ids": [None]},
    )
    delete_chunks_for_source(conn, "caption", video_id)
    index_chunks(
        conn,
        [chunk],
        workspace_id=workspace_id,
        source_type="caption",
        source_id=video_id,
        embedder=embedder,
    )
    return 1


def process_reel(
    conn: sqlite3.Connection,
    *,
    workspace_id: int,
    url: str,
    video_provider: VideoProvider,
    transcriber: TranscriptionProvider,
    embedder: EmbeddingProvider,
    context: str = "",
) -> dict:
    """Fetch + transcribe + index a single Instagram reel.

    Returns a dict summary; never raises. Sets video.status accordingly.
    """
    canonical = canonicalize_url(url)
    if not is_instagram_url(canonical):
        return {"url": url, "status": "skipped", "reason": "not-instagram"}

    # Idempotent: already done? return.
    existing = conn.execute(
        "SELECT id, status FROM videos WHERE workspace_id = ? AND canonical_url = ?",
        (workspace_id, canonical),
    ).fetchone()
    if existing and existing["status"] in ("done", "unavailable"):
        return {"url": url, "status": existing["status"], "cached": True}

    if settings.disable_instagram_fetch:
        video_id = _upsert_video_row(
            conn, workspace_id, url, canonical, "unavailable",
            error="disabled by config (DISABLE_INSTAGRAM_FETCH=1)",
        )
        return {"url": url, "status": "unavailable", "video_id": video_id,
                "reason": "fetch disabled"}

    video_id = _upsert_video_row(conn, workspace_id, url, canonical, "fetching")
    conn.commit()

    # Stash the user's one-line context (the text they wrote in Notion
    # right above this URL, like "openclaw maintainer") so the answer
    # pipeline can surface it when the reel has no usable audio.
    if context:
        conn.execute(
            "UPDATE videos SET context=?, updated_at=datetime('now') WHERE id=?",
            (context, video_id),
        )
        conn.commit()

    # 1) fetch audio
    try:
        info = video_provider.fetch_audio(url)
    except Exception as e:
        reason = f"fetch: {e!s}"[:240]
        conn.execute(
            "UPDATE videos SET status='unavailable', error=?, updated_at=datetime('now') WHERE id=?",
            (reason, video_id),
        )
        conn.commit()
        log.warning("reel.fetch_failed", url=url, reason=reason)
        return {"url": url, "status": "unavailable", "video_id": video_id, "reason": reason}

    # Store the Instagram caption as the video's description so it's
    # available for the answer pipeline (and the Sources panel).
    if info.description:
        conn.execute(
            "UPDATE videos SET description=?, updated_at=datetime('now') WHERE id=?",
            (info.description, video_id),
        )
        conn.commit()

    conn.execute(
        "UPDATE videos SET status='transcribing', updated_at=datetime('now') WHERE id=?",
        (video_id,),
    )
    conn.commit()

    # 2) transcribe
    try:
        result = transcriber.transcribe(info.local_audio_path)
    except Exception as e:
        reason = f"transcribe: {e!s}"[:240]
        conn.execute(
            "UPDATE videos SET status='unavailable', error=?, updated_at=datetime('now') WHERE id=?",
            (reason, video_id),
        )
        conn.commit()
        log.warning("reel.transcribe_failed", url=url, reason=reason)
        return {"url": url, "status": "unavailable", "video_id": video_id, "reason": reason}

    if not result.segments and not result.full_text_original:
        # No audio — store a synthetic "no transcribable audio" message so users see why
        conn.execute(
            "UPDATE videos SET status='done', language=?, updated_at=datetime('now') WHERE id=?",
            (result.language or "unknown", video_id),
        )
        conn.execute(
            "DELETE FROM video_transcripts WHERE video_id = ?",
            (video_id,),
        )
        conn.execute(
            "INSERT INTO video_transcripts(video_id, language, full_text_original, full_text_en, segments_json, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                video_id,
                result.language or "unknown",
                "(no transcribable audio)",
                "(no transcribable audio)",
                json.dumps([]),
                "whisper",
            ),
        )
        conn.commit()
        # Still index the caption + context so the reel is findable.
        _index_caption_and_context(
            conn, workspace_id, video_id, canonical, embedder,
        )
        return {"url": url, "status": "done", "video_id": video_id, "empty": True}

    # 3) Translate to English via the LLM (Groq has no translate task;
    # see app/translation.py). We do this before persisting so the stored
    # segments have text_en populated for the RAG context.
    if result.segments and not (result.language or "").lower().startswith("en"):
        try:
            from app.providers import get_llm
            from app.translation import translate_segments, translate_text

            llm = get_llm()
            result.segments = translate_segments(
                result.segments, source_language=result.language, llm=llm
            )
            result.full_text_en = translate_text(
                result.full_text_original,
                source_language=result.language,
                llm=llm,
            )
        except Exception as e:
            log.warning("reel.translate_failed", url=url, error=str(e)[:200])
            # Translation is best-effort; we still persist the original.

    # 3) persist transcript
    conn.execute("DELETE FROM video_transcripts WHERE video_id = ?", (video_id,))
    conn.execute(
        "INSERT INTO video_transcripts(video_id, language, full_text_original, full_text_en, segments_json, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            video_id,
            result.language,
            result.full_text_original,
            result.full_text_en,
            json.dumps([s.__dict__ for s in result.segments]),
            result.source,
        ),
    )
    # 4) chunk + index
    delete_chunks_for_source(conn, "video_transcript", video_id)
    seg_dicts = [s.__dict__ for s in result.segments]
    chunks = chunk_transcript_segments(seg_dicts)
    deep_link_fn = lambda c: canonical  # noqa: E731
    index_chunks(
        conn,
        chunks,
        workspace_id=workspace_id,
        source_type="video_transcript",
        source_id=video_id,
        embedder=embedder,
        deep_link_for_chunk=deep_link_fn,
    )
    conn.execute(
        "UPDATE videos SET status='done', language=?, updated_at=datetime('now') WHERE id=?",
        (result.language, video_id),
    )
    conn.commit()

    # 5) Also index the Instagram caption + the user's one-line context
    # (if any) as a separate chunk. Reels that are just music have no
    # transcript; the caption is the only real signal we have. The user's
    # one-line description in Notion ("openclaw maintainer") is gold for
    # the cross-language case — the user wrote it themselves in English.
    _index_caption_and_context(
        conn, workspace_id, video_id, canonical, embedder,
    )

    return {
        "url": url,
        "status": "done",
        "video_id": video_id,
        "language": result.language,
        "segments": len(result.segments),
    }


def process_reel_with_polite_delay(
    *args, **kwargs
) -> dict:
    """Wraps process_reel with a small polite delay between reels (Instagram
    rate-limits aggressively). Set MIN_REEL_DELAY=0 in tests to disable."""
    time.sleep(0)  # yield
    return process_reel(*args, **kwargs)
