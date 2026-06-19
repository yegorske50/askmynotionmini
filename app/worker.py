"""Resumable ingestion worker.

Polls the `ingestion_jobs` table for pending/running jobs and processes them.
Survives restarts: the job status table is the source of truth; per-reel
status rows make individual reel processing resumable.
"""

from __future__ import annotations

import signal
import time
from pathlib import Path

import structlog

from app.db import connect, get_conn
from app.ingest.notion_ingest import run_ingest
from app.providers import (
    get_embedder,
    get_notion,
    get_transcriber,
    get_video,
)

log = structlog.get_logger(__name__)


_RUNNING = True


def _stop(*_):
    global _RUNNING
    _RUNNING = False


def _claim_next_job() -> int | None:
    """Atomically mark the next pending job as running and return its id."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, current_step FROM ingestion_jobs "
            "WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE ingestion_jobs SET status='running' WHERE id = ?", (row["id"],)
        )
    return int(row["id"])


def _process_job(job_id: int) -> None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT current_step FROM ingestion_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        step = row["current_step"] or ""
    full_resync = step.startswith("full")
    try:
        run_ingest(
            conn=connect(),
            job_id=job_id,
            notion=get_notion(),
            embedder=get_embedder(),
            video_provider=get_video(),
            transcriber=get_transcriber(),
            full_resync=full_resync,
        )
    except Exception as e:
        log.exception("worker.job_failed", job_id=job_id, error=str(e)[:300])
        with get_conn() as conn:
            conn.execute(
                "UPDATE ingestion_jobs SET status='error', error=?, finished_at=datetime('now') "
                "WHERE id = ?",
                (str(e)[:300], job_id),
            )


def main_loop(poll_interval: float = 1.0) -> None:
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    log.info("worker.start")
    Path("data").mkdir(exist_ok=True)
    tick_file = Path("data/.worker.tick")
    while _RUNNING:
        try:
            job_id = _claim_next_job()
            if job_id is None:
                # also resume: jobs stuck in 'running' (worker died mid-job)
                with get_conn() as conn:
                    stuck = conn.execute(
                        "SELECT id FROM ingestion_jobs WHERE status = 'running' "
                        "ORDER BY id ASC LIMIT 1"
                    ).fetchone()
                if stuck:
                    log.info("worker.resume_stuck", job_id=int(stuck["id"]))
                    _process_job(int(stuck["id"]))
                else:
                    time.sleep(poll_interval)
                continue
            log.info("worker.start_job", job_id=job_id)
            _process_job(job_id)
            # clear the nudge file
            if tick_file.exists():
                try:
                    tick_file.unlink()
                except OSError:
                    pass
        except Exception as e:
            log.exception("worker.tick_error", error=str(e)[:300])
            time.sleep(poll_interval)
    log.info("worker.stop")


if __name__ == "__main__":
    main_loop()
