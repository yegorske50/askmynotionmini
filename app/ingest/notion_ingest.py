"""Top-level ingest orchestration.

1. Resolve the workspace (one row, id=1).
2. Walk Notion pages recursively (cap NOTION_MAX_DEPTH).
3. Persist blocks + child page links.
4. Collect Instagram URLs from page text + child pages.
5. Process each reel via the IG pipeline.
6. Update job status throughout so SSE can read it.
"""

from __future__ import annotations

import re
import sqlite3
import time

import structlog

from app.config import settings
from app.ingest.chunker import chunk_notion_blocks
from app.ingest.ig_pipeline import process_reel_with_polite_delay
from app.ingest.indexer import delete_chunks_for_source, index_chunks
from app.providers import (
    EmbeddingProvider,
    NotionSource,
    TranscriptionProvider,
    VideoProvider,
)
from app.providers.ytdlp_video import is_instagram_url

log = structlog.get_logger(__name__)


_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def _extract_instagram_urls(*texts: str) -> list[str]:
    out: list[str] = []
    for t in texts:
        if not t:
            continue
        for u in _URL_RE.findall(t):
            if is_instagram_url(u):
                out.append(u)
    # preserve order, dedupe
    seen = set()
    uniq: list[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def _set_step(conn: sqlite3.Connection, job_id: int, step: str) -> None:
    conn.execute(
        "UPDATE ingestion_jobs SET current_step = ?, status = CASE WHEN status = 'pending' THEN 'running' ELSE status END WHERE id = ?",
        (step, job_id),
    )
    conn.commit()


def _ensure_workspace(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM workspace WHERE id = 1").fetchone()
    if not row:
        raise RuntimeError(
            "Workspace not configured. POST /api/workspace first."
        )
    return 1


def run_ingest(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    notion: NotionSource,
    embedder: EmbeddingProvider,
    video_provider: VideoProvider,
    transcriber: TranscriptionProvider,
    full_resync: bool = False,
) -> None:
    """Top-level ingest loop. Updates ingestion_jobs in-place so the SSE
    endpoint can read progress."""
    workspace_id = _ensure_workspace(conn)
    ws = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
    root_page_id = ws["notion_page_id"]
    max_depth = max(1, min(int(ws["mode"] and 0 or settings.notion_max_depth), 5))

    # 1) Notion walk
    _set_step(conn, job_id, f"notion: walking pages (depth≤{max_depth})")
    pages: list = []
    skipped: list[tuple[str, str]] = []
    _walk_notion(
        notion,
        page_id=root_page_id,
        depth=0,
        max_depth=max_depth,
        parent_page_id=None,
        pages_out=pages,
        skipped_out=skipped,
    )

    # 2) Persist notion pages + blocks; collect IG URLs
    all_block_rows: list[dict] = []
    ig_urls: list[str] = []
    _texts_with_urls = 0
    for p in pages:
        if p.status == "skipped":
            conn.execute(
                "INSERT OR REPLACE INTO notion_pages(workspace_id, notion_page_id, parent_page_id, title, url, depth, last_edited_time, status, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workspace_id,
                    p.page_id,
                    p.parent_page_id,
                    p.title,
                    p.url,
                    p.depth,
                    p.last_edited_time,
                    "skipped",
                    p.error or "not shared with integration",
                ),
            )
            continue
        # upsert page
        cur = conn.execute(
            "SELECT id FROM notion_pages WHERE workspace_id = ? AND notion_page_id = ?",
            (workspace_id, p.page_id),
        )
        np_id_row = cur.fetchone()
        if np_id_row:
            np_id = int(np_id_row["id"])
            conn.execute(
                "UPDATE notion_pages SET title=?, url=?, depth=?, last_edited_time=?, "
                "last_ingested_at=datetime('now'), status='ingested', error=NULL WHERE id = ?",
                (p.title, p.url, p.depth, p.last_edited_time, np_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO notion_pages(workspace_id, notion_page_id, parent_page_id, title, url, depth, last_edited_time, last_ingested_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 'ingested')",
                (
                    workspace_id,
                    p.page_id,
                    p.parent_page_id,
                    p.title,
                    p.url,
                    p.depth,
                    p.last_edited_time,
                ),
            )
            np_id = int(cur.lastrowid)

        # blocks: incremental — only reprocess changed/new unless full_resync
        existing_block_ids = {
            r["block_id"]
            for r in conn.execute(
                "SELECT block_id FROM notion_blocks WHERE notion_page_id = ?", (p.page_id,)
            ).fetchall()
        }
        for b in p.blocks:
            if b.block_id in existing_block_ids and not full_resync:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO notion_blocks(notion_page_id, block_id, type, text, deep_link) "
                "VALUES (?, ?, ?, ?, ?)",
                (p.page_id, b.block_id, b.type, b.text, b.deep_link),
            )
            all_block_rows.append(
                {
                    "block_id": b.block_id,
                    "type": b.type,
                    "text": b.text,
                    "deep_link": b.deep_link,
                }
            )
            # also collect IG URLs in block text
            for u in _extract_instagram_urls(b.text):
                if u not in ig_urls:
                    ig_urls.append(u)
            # diagnostic: how many blocks contain any URL?
            if b.text and ("instagram.com" in b.text or "instagr.am" in b.text):
                _texts_with_urls += 1

    log.info(
        "notion_ingest.ig_url_scan",
        total_ig_urls=len(ig_urls),
        blocks_with_instagram_text=_texts_with_urls,
        total_blocks_scanned=len(all_block_rows),
        full_resync=full_resync,
    )

    # 3) chunk + index blocks
    _set_step(conn, job_id, f"indexing {len(all_block_rows)} blocks")
    if all_block_rows:
        # Group by page so chunks carry correct deep links
        per_page: dict[str, list[dict]] = {}
        # Simpler: re-look up page_id by deep_link basename
        for b in all_block_rows:
            page_id = _resolve_page_id_for_block(conn, b["block_id"]) or root_page_id
            per_page.setdefault(page_id, []).append(b)
        for page_id, blocks in per_page.items():
            np_id_row = conn.execute(
                "SELECT id FROM notion_pages WHERE workspace_id = ? AND notion_page_id = ?",
                (workspace_id, page_id),
            ).fetchone()
            if not np_id_row:
                continue
            np_id = int(np_id_row["id"])
            # delete existing chunks for this page (we re-indexed changed blocks)
            delete_chunks_for_source(conn, "notion_block", np_id)
            chunks = chunk_notion_blocks(blocks)
            index_chunks(
                conn,
                chunks,
                workspace_id=workspace_id,
                source_type="notion_block",
                source_id=np_id,
                embedder=embedder,
            )
    conn.commit()

    # 4) Update Notion job counters
    conn.execute(
        "UPDATE ingestion_jobs SET total_blocks = ?, done_blocks = ? WHERE id = ?",
        (len(all_block_rows), len(all_block_rows), job_id),
    )
    conn.commit()

    # 5) Process reels
    if settings.disable_instagram_fetch:
        _set_step(conn, job_id, "instagram: fetch disabled (config)")
        ig_urls = []

    # On a full re-ingest, reset every previously-finished or previously-
    # failed video's status so process_reel's cache-skip doesn't short-
    # circuit. Without this, a 'force full re-ingest' would silently skip
    # every previously-failed reel and 'complete' in 0 seconds with the
    # same old errors visible in the UI.
    if full_resync and ig_urls:
        n_reset = conn.execute(
            "UPDATE videos SET status='queued', error=NULL, "
            "updated_at=datetime('now') "
            "WHERE workspace_id = ? AND status IN ('done', 'unavailable')",
            (workspace_id,),
        ).rowcount
        if n_reset:
            log.info("notion_ingest.reset_cached_reels", count=n_reset)
        conn.commit()

    conn.execute(
        "UPDATE ingestion_jobs SET total_videos = ? WHERE id = ?",
        (len(ig_urls), job_id),
    )
    conn.commit()
    for i, url in enumerate(ig_urls, 1):
        _set_step(conn, job_id, f"reel {i}/{len(ig_urls)}: {url[:60]}")
        try:
            process_reel_with_polite_delay(
                conn,
                workspace_id=workspace_id,
                url=url,
                video_provider=video_provider,
                transcriber=transcriber,
                embedder=embedder,
            )
        except Exception as e:
            log.warning("reel.unhandled", url=url, error=str(e)[:200])
        # job-level progress
        done = conn.execute(
            "SELECT COUNT(*) AS c FROM videos WHERE workspace_id = ? AND status IN ('done', 'unavailable')",
            (workspace_id,),
        ).fetchone()["c"]
        conn.execute(
            "UPDATE ingestion_jobs SET done_videos = ? WHERE id = ?", (done, job_id)
        )
        conn.commit()
        time.sleep(0)  # yield

    # 6) Finalize
    total_chunks = conn.execute(
        "SELECT COUNT(*) AS c FROM chunks WHERE workspace_id = ?", (workspace_id,)
    ).fetchone()["c"]
    conn.execute(
        "UPDATE ingestion_jobs SET status='done', indexed_chunks=?, "
        "current_step='done', finished_at=datetime('now') WHERE id = ?",
        (total_chunks, job_id),
    )
    conn.execute(
        "UPDATE workspace SET notion_last_edited_time = ? WHERE id = 1",
        (pages[0].last_edited_time if pages and pages[0].last_edited_time else None,),
    )
    conn.commit()
    log.info("ingest.done", job_id=job_id, chunks=total_chunks, reels=len(ig_urls))


def _resolve_page_id_for_block(conn: sqlite3.Connection, block_id: str) -> str | None:
    row = conn.execute(
        "SELECT notion_page_id FROM notion_blocks WHERE block_id = ? LIMIT 1",
        (block_id,),
    ).fetchone()
    return row["notion_page_id"] if row else None


def _walk_notion(
    notion: NotionSource,
    *,
    page_id: str,
    depth: int,
    max_depth: int,
    parent_page_id: str | None,
    pages_out: list,
    skipped_out: list[tuple[str, str]],
) -> None:
    page = notion.get_page(page_id, depth=depth)
    if page.status in ("skipped", "error"):
        skipped_out.append((page.page_id, page.error or "unavailable"))
        pages_out.append(page)
        return
    page.parent_page_id = parent_page_id
    pages_out.append(page)
    if depth + 1 > max_depth:
        return
    for child_id in page.child_page_ids:
        _walk_notion(
            notion,
            page_id=child_id,
            depth=depth + 1,
            max_depth=max_depth,
            parent_page_id=page.page_id,
            pages_out=pages_out,
            skipped_out=skipped_out,
        )
