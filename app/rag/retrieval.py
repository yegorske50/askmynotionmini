"""Hybrid retrieval: sqlite-vec (cosine) + FTS5 (BM25) fused with RRF.

We pull top-K from each channel, then take a weighted reciprocal-rank-fusion
score. Citations are returned in their merged order, with optional LLM
reranking of the top-N (env ENABLE_LLM_RERANK=1).
"""

from __future__ import annotations

import sqlite3
import struct
import structlog
from dataclasses import dataclass

from app.providers import EmbeddingProvider, LLMProvider

log = structlog.get_logger(__name__)


@dataclass
class Hit:
    chunk_id: int
    text_original: str
    text_en: str | None
    source_type: str
    source_id: int
    block_id: str | None
    video_id: int | None
    language: str | None
    start_sec: float | None
    end_sec: float | None
    deep_link: str
    rrf_score: float
    title: str
    snippet_max_chars: int = 280


def _escape_fts(q: str) -> str:
    """Wrap each token in quotes for FTS5 literal matching (avoids syntax
    errors when the user types something the parser dislikes)."""
    tokens = [t for t in q.split() if t]
    if not tokens:
        return '""'
    return " ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


def _build_title(conn: sqlite3.Connection, chunk: sqlite3.Row) -> str:
    if chunk["source_type"] == "notion_block":
        row = conn.execute(
            "SELECT np.title, nb.type FROM notion_blocks nb "
            "JOIN notion_pages np ON np.notion_page_id = nb.notion_page_id "
            "WHERE nb.block_id = ? LIMIT 1",
            (chunk["block_id"],),
        ).fetchone()
        if row:
            return f"{row['title']} ({row['type']})"
    if chunk["source_type"] in ("video_transcript", "caption"):
        v = conn.execute(
            "SELECT canonical_url, author FROM videos WHERE id = ?", (chunk["video_id"],)
        ).fetchone()
        if v:
            return f"Reel — {v['author'] or v['canonical_url']}"
    return chunk["source_type"]


def hybrid_retrieve(
    conn: sqlite3.Connection,
    *,
    query: str,
    workspace_id: int,
    embedder: EmbeddingProvider,
    top_k_vec: int = 50,
    top_k_fts: int = 50,
    final_k: int = 10,
    rrf_k: int = 60,
) -> list[Hit]:
    """Return the top final_k hits by RRF-fused vector + keyword ranks."""
    if not query.strip():
        return []

    # 1) vector channel — if the embedder (which hits the MiniMax API) is
    # unreachable, we fall back to FTS-only results so the user still
    # sees something. Without this, a single DNS hiccup turns the chat
    # into an empty bubble.
    try:
        qvec = embedder.embed_query(query)
        # sqlite-vec v0.1.x cosine `MATCH` isn't reliably available across
        # builds, so we do k-NN in Python. With ≤10k chunks per workspace
        # this is fast enough on the Mac profile.
        vec_hits = _vector_search(conn, qvec, workspace_id, top_k_vec)
    except Exception as e:
        log.warning("retrieval.vector_failed", error=str(e)[:200])
        vec_hits = []

    # 2) keyword channel (FTS5 BM25)
    fts_query = _escape_fts(query)
    fts_rows = conn.execute(
        """
        SELECT c.id AS chunk_id
        FROM chunks_fts f
        JOIN chunks c ON c.id = f.rowid
        WHERE chunks_fts MATCH ? AND c.workspace_id = ?
        ORDER BY bm25(chunks_fts) ASC
        LIMIT ?
        """,
        (fts_query, workspace_id, top_k_fts),
    ).fetchall()

    # 3) RRF
    fused: dict[int, float] = {}
    for rank, r in enumerate(vec_hits, 1):
        fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0.0) + 1.0 / (rrf_k + rank)
    for rank, r in enumerate(fts_rows, 1):
        fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0.0) + 1.0 / (rrf_k + rank)

    ordered = sorted(fused.items(), key=lambda kv: -kv[1])[:final_k]

    # 4) Hydrate
    hits: list[Hit] = []
    for cid, score in ordered:
        row = conn.execute(
            "SELECT * FROM chunks WHERE id = ? AND workspace_id = ?",
            (cid, workspace_id),
        ).fetchone()
        if not row:
            continue
        title = _build_title(conn, row)
        hits.append(
            Hit(
                chunk_id=int(row["id"]),
                text_original=row["text_original"],
                text_en=row["text_en"],
                source_type=row["source_type"],
                source_id=int(row["source_id"]),
                block_id=row["block_id"],
                video_id=int(row["video_id"]) if row["video_id"] is not None else None,
                language=row["language"],
                start_sec=row["start_sec"],
                end_sec=row["end_sec"],
                deep_link=row["deep_link"],
                rrf_score=score,
                title=title,
            )
        )
    return hits


def _vector_search(
    conn: sqlite3.Connection,
    qvec: list[float],
    workspace_id: int,
    k: int,
) -> list[sqlite3.Row]:
    """Compute cosine similarity in Python over chunks_vec.

    sqlite-vec v0.1.x doesn't expose a `MATCH` operator across the embedded
    version in all builds, so we do the k-NN in Python. With ≤~10k chunks
    per workspace this is fast enough on the Mac profile and keeps the
    implementation portable.
    """

    rows = conn.execute(
        "SELECT cv.chunk_id, cv.embedding FROM chunks_vec cv "
        "JOIN chunks c ON c.id = cv.chunk_id WHERE c.workspace_id = ?",
        (workspace_id,),
    ).fetchall()

    scored: list[tuple[int, float]] = []
    for r in rows:
        emb_blob = r["embedding"]
        # sqlite-vec stores float32 little-endian packed BLOBs.
        emb = list(struct.unpack(f"<{len(emb_blob) // 4}f", emb_blob))
        # both sides are already L2-normalized (e5 default), so dot == cosine
        s = 0.0
        for a, b in zip(qvec, emb, strict=False):
            s += a * b
        scored.append((r["chunk_id"], -s))  # distance = -similarity
    scored.sort(key=lambda x: x[1])

    out: list[sqlite3.Row] = []
    for cid, dist in scored[:k]:
        # Lightweight Row-like object supporting both ["k"] and .k.
        out.append(_VecRow(chunk_id=cid, distance=dist))
    return out


class _VecRow:
    __slots__ = ("chunk_id", "distance")

    def __init__(self, chunk_id: int, distance: float):
        self.chunk_id = chunk_id
        self.distance = distance

    def __getitem__(self, key: str):
        return getattr(self, key)


def maybe_rerank(
    hits: list[Hit],
    *,
    query: str,
    llm: LLMProvider,
    top_n: int = 15,
) -> list[Hit]:
    """Optional MiniMax-based rerank. Off by default."""
    if not hits:
        return hits
    head = hits[:top_n]
    tail = hits[top_n:]
    options = "\n".join(
        f"[{i+1}] {h.text_original[:240]}" for i, h in enumerate(head)
    )
    prompt = (
        "You are a reranker. Reorder the candidate passages by how well they "
        f"answer the question. Reply with the indices in order, comma-separated, "
        f"no commentary. Question: {query}\n\n{options}"
    )
    try:
        out = llm.complete(
            [__import__("app.providers.base", fromlist=["ChatMessage"]).ChatMessage("user", prompt)],
            temperature=0.0,
            max_tokens=64,
        ).strip()
        order: list[int] = []
        for tok in out.split(","):
            try:
                idx = int(tok.strip()) - 1
                if 0 <= idx < len(head) and idx not in order:
                    order.append(idx)
            except ValueError:
                continue
        # append any not mentioned
        for i in range(len(head)):
            if i not in order:
                order.append(i)
        reranked = [head[i] for i in order] + tail
        return reranked
    except Exception:
        return hits
