"""FastAPI app: API + static frontend (prebuilt web/dist).

No auth, single user. Optional APP_PASSWORD gate.
"""

from __future__ import annotations

import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.db import get_conn
from app.models import (
    IngestOut,
    IngestStatusOut,
    MessageIn,
    SourceNotionPageOut,
    SourcesOut,
    SourceVideoOut,
    TranscriptIn,
    WorkspaceOut,
    WorkspaceSetIn,
)
from app.providers.ytdlp_video import canonicalize_url
from app.rag import stream_answer

log = structlog.get_logger(__name__)


# ─── Lifespan: warm up DB (and force migrations) ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Touch DB so migrations run.
    with get_conn() as _:
        pass
    log.info("app.startup", host=settings.host, port=settings.port)
    yield


app = FastAPI(
    title="AskMyNotion",
    version="0.1.0",
    description="Local RAG over your Notion + Instagram reels.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Optional password gate ──────────────────────────────────────────────────
def _check_password(request: Request) -> None:
    if not settings.app_password:
        return
    auth = request.headers.get("authorization") or ""
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif auth:
        token = auth
    if not token or not secrets.compare_digest(token, settings.app_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing app password",
        )


# ─── /health ──────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    info: dict = {"status": "ok"}
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()
            info["chunks"] = int(row["c"])
            row = conn.execute("SELECT COUNT(*) AS c FROM videos").fetchone()
            info["videos"] = int(row["c"])
    except Exception as e:
        info["status"] = "degraded"
        info["error"] = str(e)[:200]
    return info


# ─── /api/workspace ──────────────────────────────────────────────────────────
@app.post("/api/workspace", response_model=WorkspaceOut)
def set_workspace(body: WorkspaceSetIn, _=Depends(_check_password)):
    page_id = _extract_page_id(body.notion_page_url)
    if not page_id:
        raise HTTPException(400, "could not parse NOTION_PAGE_URL")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO workspace(id, name, notion_page_id, notion_page_url, mode) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
            "notion_page_id=excluded.notion_page_id, notion_page_url=excluded.notion_page_url, "
            "mode=excluded.mode",
            (body.name, page_id, body.notion_page_url, "token" if body.notion_token else "public"),
        )
    return get_workspace()


@app.get("/api/workspace", response_model=WorkspaceOut)
def get_workspace(_=Depends(_check_password)):
    with get_conn() as conn:
        ws = conn.execute("SELECT * FROM workspace WHERE id = 1").fetchone()
        if not ws:
            raise HTTPException(404, "workspace not set; POST /api/workspace")
        pages = conn.execute("SELECT COUNT(*) AS c FROM notion_pages").fetchone()["c"]
        videos = conn.execute("SELECT COUNT(*) AS c FROM videos").fetchone()["c"]
        chunks = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
    return WorkspaceOut(
        name=ws["name"],
        notion_page_id=ws["notion_page_id"],
        notion_page_url=ws["notion_page_url"],
        mode=ws["mode"],
        counts={"pages": int(pages), "videos": int(videos), "chunks": int(chunks)},
    )


# ─── /api/ingest ─────────────────────────────────────────────────────────────
@app.post("/api/ingest", response_model=IngestOut)
def post_ingest(_=Depends(_check_password)):
    return IngestOut(job_id=_enqueue_job(full_resync=False))


@app.post("/api/resync", response_model=IngestOut)
def post_resync(_=Depends(_check_password)):
    return IngestOut(job_id=_enqueue_job(full_resync=True))


def _enqueue_job(*, full_resync: bool) -> int:
    with get_conn() as conn:
        if not conn.execute("SELECT id FROM workspace WHERE id = 1").fetchone():
            raise HTTPException(400, "workspace not set")
        cur = conn.execute(
            "INSERT INTO ingestion_jobs(workspace_id, status, current_step) VALUES (1, 'pending', 'queued')"
        )
        job_id = int(cur.lastrowid)
        # store full_resync hint in current_step prefix; worker reads it
        flag = "full" if full_resync else "incr"
        conn.execute(
            "UPDATE ingestion_jobs SET current_step = ? WHERE id = ?",
            (f"{flag}:queued", job_id),
        )
    # nudge the worker via a tiny file (cross-platform, no Redis)
    Path("data").mkdir(exist_ok=True)
    Path("data/.worker.tick").write_text(str(job_id))
    return job_id


@app.get("/api/ingest/status")
def get_ingest_status(_=Depends(_check_password), poll: bool = False):
    """SSE: emits job + per-source progress until the job is done/error.
    When called with `?poll=1`, returns a single JSON snapshot instead — used
    by the UI's polling fallback when EventSource isn't available.
    """
    if poll:
        return _ingest_status_snapshot()
    def gen():
        last_payload = None
        while True:
            with get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM ingestion_jobs WHERE workspace_id = 1 ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if not row:
                    payload = {"status": "idle"}
                else:
                    payload = IngestStatusOut(
                        job_id=int(row["id"]),
                        status=row["status"],
                        total_blocks=int(row["total_blocks"]),
                        done_blocks=int(row["done_blocks"]),
                        total_videos=int(row["total_videos"]),
                        done_videos=int(row["done_videos"]),
                        indexed_chunks=int(row["indexed_chunks"]),
                        current_step=row["current_step"] or "",
                        error=row["error"],
                    ).model_dump()
                    if row["status"] in ("done", "error"):
                        payload["final"] = True

                # also per-reel statuses
                reels = conn.execute(
                    "SELECT id, source_url, status, error FROM videos WHERE workspace_id = 1 ORDER BY id"
                ).fetchall()
                payload["reels"] = [dict(r) for r in reels]
            data = json.dumps(payload)
            if data == last_payload:
                # heartbeat
                yield ": heartbeat\n\n"
            else:
                yield f"data: {data}\n\n"
                last_payload = data
            if payload.get("status") in ("done", "error", "idle") and payload.get("final"):
                return
            import time
            time.sleep(0.6)

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ingest_status_snapshot() -> dict:
    """Single JSON snapshot of the latest job + per-reel statuses."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM ingestion_jobs WHERE workspace_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            payload: dict = {"status": "idle"}
        else:
            payload = IngestStatusOut(
                job_id=int(row["id"]),
                status=row["status"],
                total_blocks=int(row["total_blocks"]),
                done_blocks=int(row["done_blocks"]),
                total_videos=int(row["total_videos"]),
                done_videos=int(row["done_videos"]),
                indexed_chunks=int(row["indexed_chunks"]),
                current_step=row["current_step"] or "",
                error=row["error"],
            ).model_dump()
        reels = conn.execute(
            "SELECT id, source_url, status, error FROM videos WHERE workspace_id = 1 ORDER BY id"
        ).fetchall()
        payload["reels"] = [dict(r) for r in reels]
    return payload


# ─── /api/sources ────────────────────────────────────────────────────────────
@app.get("/api/sources", response_model=SourcesOut)
def list_sources(_=Depends(_check_password)):
    with get_conn() as conn:
        pages = conn.execute(
            "SELECT p.id, p.notion_page_id, p.title, p.url, p.depth, p.status, "
            "(SELECT COUNT(*) FROM notion_blocks b WHERE b.notion_page_id = p.notion_page_id) AS block_count "
            "FROM notion_pages p WHERE p.workspace_id = 1 ORDER BY p.depth, p.title"
        ).fetchall()
        videos = conn.execute(
            "SELECT v.id, v.source_url, v.author, v.status, v.error, v.language, "
            "EXISTS(SELECT 1 FROM video_transcripts t WHERE t.video_id = v.id) AS has_transcript "
            "FROM videos v WHERE v.workspace_id = 1 ORDER BY v.id"
        ).fetchall()
    return SourcesOut(
        pages=[SourceNotionPageOut(**dict(p)) for p in pages],
        videos=[SourceVideoOut(**dict(v)) for v in videos],
    )


@app.post("/api/sources/{source_id}/retry")
def retry_source(source_id: int, _=Depends(_check_password)):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, source_url FROM videos WHERE id = ? AND workspace_id = 1", (source_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "video not found")
        conn.execute(
            "UPDATE videos SET status='queued', error=NULL, updated_at=datetime('now') WHERE id = ?",
            (source_id,),
        )
    _enqueue_job(full_resync=False)
    return {"ok": True, "video_id": source_id}


@app.post("/api/sources/{source_id}/transcript")
def paste_transcript(source_id: int, body: TranscriptIn, _=Depends(_check_password)):
    """Manually paste a transcript for a failed reel — stored as if from whisper."""
    import json as _json

    segs = [
        {
            "start": 0.0,
            "end": max(1.0, float(len(body.text)) / 15.0),
            "text_original": body.text.strip(),
            "text_en": body.text.strip(),
            "language": body.language or "en",
        }
    ]
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM videos WHERE id = ? AND workspace_id = 1", (source_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "video not found")
        conn.execute("DELETE FROM video_transcripts WHERE video_id = ?", (source_id,))
        conn.execute(
            "INSERT INTO video_transcripts(video_id, language, full_text_original, full_text_en, segments_json, source) "
            "VALUES (?, ?, ?, ?, ?, 'manual')",
            (source_id, body.language or "en", body.text, body.text, _json.dumps(segs)),
        )
        conn.execute(
            "UPDATE videos SET status='done', error=NULL, language=?, updated_at=datetime('now') WHERE id = ?",
            (body.language or "en", source_id),
        )
        # (re-)index the manual transcript
        from app.ingest.chunker import chunk_transcript_segments
        from app.ingest.indexer import delete_chunks_for_source, index_chunks
        from app.providers import get_embedder

        delete_chunks_for_source(conn, "video_transcript", source_id)
        chunks = chunk_transcript_segments(segs)
        index_chunks(
            conn,
            chunks,
            workspace_id=1,
            source_type="video_transcript",
            source_id=source_id,
            embedder=get_embedder(),
            deep_link_for_chunk=lambda c: row["source_url"] if hasattr(row, "keys") else canonicalize_url(row["source_url"]) if False else canonicalize_url(conn.execute("SELECT source_url FROM videos WHERE id=?", (source_id,)).fetchone()["source_url"]),
        )
    return {"ok": True, "video_id": source_id}


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int, _=Depends(_check_password)):
    from app.ingest.indexer import delete_chunks_for_source
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, source_type FROM videos WHERE id = ? AND workspace_id = 1", (source_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "video not found")
        delete_chunks_for_source(conn, "video_transcript", source_id)
        conn.execute("DELETE FROM video_transcripts WHERE video_id = ?", (source_id,))
        conn.execute("DELETE FROM videos WHERE id = ?", (source_id,))
    return {"ok": True}


# ─── /api/conversations ─────────────────────────────────────────────────────
class _StartBody(BaseModel):
    title: str | None = None


@app.get("/api/conversations")
def list_conversations(_=Depends(_check_password)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM conversations ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/conversations")
def start_conversation(body: _StartBody = _StartBody(), _=Depends(_check_password)):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations(title) VALUES (?)",
            (body.title or "New chat",),
        )
        cid = int(cur.lastrowid)
    return {"id": cid}


@app.get("/api/conversations/{cid}")
def get_conversation(cid: int, _=Depends(_check_password)):
    with get_conn() as conn:
        c = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if not c:
            raise HTTPException(404, "not found")
        msgs = conn.execute(
            "SELECT id, role, content, citations_json, model, created_at "
            "FROM messages WHERE conversation_id = ? ORDER BY id",
            (cid,),
        ).fetchall()
    out = dict(c)
    out["messages"] = []
    for m in msgs:
        d = dict(m)
        if d.get("citations_json"):
            try:
                d["citations"] = json.loads(d["citations_json"])
            except Exception:
                d["citations"] = []
        out["messages"].append(d)
    return out


@app.post("/api/conversations/{cid}/messages")
def post_message(cid: int, body: MessageIn, _=Depends(_check_password)):
    def gen():
        for ev in stream_answer(
            question=body.content,
            answer_language=body.answer_language,
            conversation_id=cid,
        ):
            payload: dict = {}
            if ev.delta:
                payload = {"type": "delta", "delta": ev.delta}
            else:
                payload = {
                    "type": "final",
                    "sources": [c.__dict__ for c in (ev.sources or [])],
                    "not_found": ev.not_found,
                }
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ─── Static frontend ─────────────────────────────────────────────────────────
_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@app.get("/")
def index():
    idx = _DIST / "index.html"
    if not idx.exists():
        return JSONResponse(
            {
                "error": "frontend not built",
                "hint": "run `make build-frontend` (requires node 20+)",
            },
            status_code=503,
        )
    return FileResponse(idx)


# Serve hashed assets under /assets and any other static files.
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


# ─── Helpers ────────────────────────────────────────────────────────────────
def _extract_page_id(url_or_id: str) -> str | None:
    """Accept 32-char hex (with or without dashes) OR a Notion URL."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    if "notion.so" in s or "notion.com" in s:
        # last path segment, strip query
        last = s.rstrip("/").split("/")[-1].split("?")[0]
        # remove title (everything after -)
        last = last.split("-")[-1]
        last = last.replace("-", "")
        if len(last) == 32 and all(c in "0123456789abcdefABCDEF" for c in last):
            return _with_dashes(last)
        return None
    s2 = s.replace("-", "")
    if len(s2) == 32 and all(c in "0123456789abcdefABCDEF" for c in s2):
        return _with_dashes(s2)
    return s or None


def _with_dashes(hex32: str) -> str:
    return f"{hex32[0:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:32]}"
