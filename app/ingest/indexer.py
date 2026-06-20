"""Persist chunks (and their vectors) into SQLite + sqlite-vec + FTS5.

The shape mirrors the schema in app/db/schema.sql. We always re-embed and
upsert, but FTS5 is rebuilt incrementally: rows in chunks_fts are joined
manually at query time (content=''), so we maintain a parallel chunks_fts_rowid
mapping by using the same chunk_id. To keep FTS5 simple we store the same row
id on insert.
"""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass

from app.ingest.chunker import Chunk
from app.providers import EmbeddingProvider


def _pack_vec(vec: list[float]) -> bytes:
    """Pack a list of Python floats into a little-endian float32 blob.

    sqlite-vec's `vec0` virtual table accepts two binary forms for vectors:
    a JSON string or a float32 little-endian packed BLOB whose length is
    divisible by 4. We use the packed form (smaller + faster to scan).
    """
    return struct.pack(f"<{len(vec)}f", *vec)


@dataclass
class IndexedChunk:
    chunk_id: int
    source_type: str
    source_id: int
    block_id: str | None
    video_id: int | None
    text_original: str
    text_en: str | None
    language: str | None
    start_sec: float | None
    end_sec: float | None
    deep_link: str


def index_chunks(
    conn: sqlite3.Connection,
    chunks: list[Chunk],
    *,
    workspace_id: int,
    source_type: str,
    source_id: int,
    embedder: EmbeddingProvider,
    deep_link_for_chunk: callable | None = None,  # type: ignore[type-arg]
) -> list[IndexedChunk]:
    """Embed and persist a list of Chunks. Returns the persisted rows."""
    if not chunks:
        return []

    texts = [c.text_original for c in chunks]
    vectors = embedder.embed_passages(texts)

    persisted: list[IndexedChunk] = []
    for chunk, vec in zip(chunks, vectors, strict=False):
        deep_link = chunk.meta.get("deep_link") if chunk.meta else None
        if not deep_link and deep_link_for_chunk:
            deep_link = deep_link_for_chunk(chunk)
        if not deep_link:
            deep_link = ""

        block_id_val = chunk.meta.get("block_ids", [None])[0] if chunk.meta else None
        video_id_val = source_id if source_type in ("video_transcript", "caption") else None

        cur = conn.execute(
            """
            INSERT INTO chunks(
                workspace_id, source_type, source_id, block_id, video_id,
                text_original, text_en, language, start_sec, end_sec, deep_link
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                source_type,
                source_id,
                block_id_val,
                video_id_val,
                chunk.text_original,
                chunk.text_en,
                chunk.language,
                chunk.start_sec,
                chunk.end_sec,
                deep_link,
            ),
        )
        chunk_id = int(cur.lastrowid)
        # sqlite-vec
        conn.execute(
            "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, _pack_vec(vec)),
        )
        # FTS5 (rowid-aligned with chunks.id)
        conn.execute(
            "INSERT INTO chunks_fts(rowid, text_original, text_en) VALUES (?, ?, ?)",
            (chunk_id, chunk.text_original, chunk.text_en or ""),
        )
        persisted.append(
            IndexedChunk(
                chunk_id=chunk_id,
                source_type=source_type,
                source_id=source_id,
                block_id=block_id_val,
                video_id=video_id_val,
                text_original=chunk.text_original,
                text_en=chunk.text_en,
                language=chunk.language,
                start_sec=chunk.start_sec,
                end_sec=chunk.end_sec,
                deep_link=deep_link,
            )
        )
    return persisted


def delete_chunks_for_source(
    conn: sqlite3.Connection, source_type: str, source_id: int
) -> int:
    cur = conn.execute(
        "SELECT id FROM chunks WHERE source_type = ? AND source_id = ?",
        (source_type, source_id),
    )
    ids = [r[0] for r in cur.fetchall()]
    if not ids:
        return 0
    qmarks = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM chunks WHERE id IN ({qmarks})", ids)
    conn.execute(f"DELETE FROM chunks_vec WHERE chunk_id IN ({qmarks})", ids)
    # FTS5 delete is wrapped in try/except so a contentless FTS5 table
    # (old schema) doesn't crash the whole indexer. The migration in
    # app/db/connection.py drops the contentless table on next connect()
    # so this branch only runs once for pre-migration DBs.
    try:
        conn.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({qmarks})", ids)
    except sqlite3.OperationalError:
        pass
    return len(ids)
