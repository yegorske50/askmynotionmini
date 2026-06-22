"""SQLite connection management with sqlite-vec + FTS5 support.

We open one connection per request/worker iteration and rely on SQLite's thread
safety (we set `check_same_thread=False` and serialize via a per-connection mutex
when running with the worker). WAL mode is enabled for concurrent reads while
the worker writes.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

_LOCK = threading.Lock()
_INITED: set[str] = set()


def _resolve_db_path() -> str:
    p = Path(settings.db_path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def connect() -> sqlite3.Connection:
    """Open a new SQLite connection with the project's pragmas applied."""
    path = _resolve_db_path()
    # Allow extension loading (sqlite-vec).
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-20000")  # ~20MB page cache
    _ensure_initialized(conn, path)
    return conn


def _ensure_initialized(conn: sqlite3.Connection, path: str) -> None:
    """Run schema migrations + load sqlite-vec exactly once per db file path.

    We always reload the sqlite-vec extension on every new connection (the
    extension is per-connection in SQLite). The schema, however, only needs to
    be re-applied when the path changes or after a reset_db() call.
    """
    # Always load the extension on every connection.
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception as e:  # pragma: no cover - depends on platform
        raise RuntimeError(
            "Failed to load sqlite-vec extension. Make sure the 'sqlite-vec' "
            "package is installed and built for your Python version."
        ) from e
    if path in _INITED:
        return
    with _LOCK:
        if path in _INITED:
            return
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            conn.executescript(f.read())
        # Lightweight migrations for older DBs (additive columns only).
        for col_sql in (
            "ALTER TABLE ingestion_jobs ADD COLUMN debug_json TEXT",
            "ALTER TABLE videos ADD COLUMN description TEXT",
            "ALTER TABLE videos ADD COLUMN context TEXT",
        ):
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migration: if chunks_fts is a contentless FTS5 table from the
        # old schema (`content=''`), drop it so the new schema recreates
        # it as a contentful table. Without this, DELETE on the old
        # contentless FTS5 raises "cannot DELETE from contentless fts5
        # table" and silently corrupts the keyword index.
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
            ).fetchone()
            if row and row[0] and "content=''" in row[0].replace('"', '').replace("'", ''):
                # Old contentless table — drop and recreate via schema
                # (the schema already ran CREATE IF NOT EXISTS, so we
                # need to drop first to force the new shape).
                conn.execute("DROP TABLE chunks_fts")
                with open(schema_path, encoding="utf-8") as f:
                    conn.executescript(f.read())
        except Exception:
            pass
        _INITED.add(path)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def reset_db() -> None:
    """Hard-reset the database. Used by tests and the seed script."""
    path = _resolve_db_path()
    with _LOCK:
        # Clear the init cache for this path AND any path that might be in it,
        # so the next connect() re-runs the schema and reloads sqlite-vec.
        _INITED.clear()
    for ext in (path, path + "-wal", path + "-shm", path + "-journal"):
        try:
            os.remove(ext)
        except FileNotFoundError:
            pass
