"""Tiny CLI: `python -m app.cli ingest` enqueues a job using the current .env."""

from __future__ import annotations

import json
import sys

import httpx

from app.config import settings


def _enqueue(full: bool) -> int:
    path = "/api/resync" if full else "/api/ingest"
    url = f"http://{settings.host}:{settings.port}{path}"
    r = httpx.post(url, headers=_auth_headers(), timeout=10.0)
    r.raise_for_status()
    return int(r.json()["job_id"])


def _auth_headers() -> dict:
    if not settings.app_password:
        return {}
    return {"Authorization": f"Bearer {settings.app_password}"}


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "ingest":
        full = "--full" in argv
        job_id = _enqueue(full)
        print(json.dumps({"job_id": job_id, "full": full}))
        return 0
    if cmd == "seed":
        from scripts.seed_demo import seed

        seed()
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
