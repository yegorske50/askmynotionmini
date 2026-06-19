"""Pytest config + fixtures.

We default to mock providers + an isolated temp DB so tests run with zero
network and no large model downloads. The same `app` package is imported in
both modes; the env vars flip them into mock state before any import.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Force mock providers + isolated temp DB before app imports.
_tmpdir = tempfile.mkdtemp(prefix="askmynotion-tests-")
os.environ.setdefault("MINIMAX_MOCK_PROVIDERS", "1")
os.environ.setdefault("TEST_FAST", "1")
os.environ.setdefault("DB_PATH", str(Path(_tmpdir) / "test.db"))
os.environ.setdefault("MEDIA_CACHE_DIR", str(Path(_tmpdir) / "media"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Now safe to import the app.
import pytest  # noqa: E402

from app import providers  # noqa: E402
from app.db import reset_db  # noqa: E402
from scripts.seed_demo import seed as seed_demo  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    # Re-init the temp DB for each test, then run the seed.
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path / "media"))
    providers.reset_providers()
    # Force-reinit connection cache by re-importing the connection module.
    from app.db import connection as _conn_mod
    _conn_mod._INITED.clear()
    reset_db()
    seed_demo(force_reset=False)
    yield
    _conn_mod._INITED.clear()


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
