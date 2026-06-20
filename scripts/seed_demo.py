"""Seed a tiny demo corpus so a reviewer can see the full flow with NO real
credentials. Idempotent: re-running clears the demo workspace and reloads.

What it installs:
- 1 mock Notion page ("Demo Notion Page") with 3 text blocks
- 3 mock Instagram reels: English, Hindi, Telugu — each with hand-written
  timestamped segments (original + English) registered with the mock
  transcriber. A small silent wav is written into media_cache/ so the
  provider chain has a real file.
- Indexes everything via the real indexer, with the real (mock) embedder,
  so the vector/FTS stores are populated and the chat flow is real.
"""

from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

# IMPORTANT: force the mock providers BEFORE any `app.*` import, regardless
# of what's in the user's .env. The seed is meant to be runnable with no
# real credentials — the demo reels (DEMO_EN_1 etc.) are placeholder URLs
# that don't exist on Instagram, and the demo Notion page id
# ("mock-page-0001") is not a real Notion UUID. If we let the factory use
# the real Notion / yt-dlp providers, both will fail.
os.environ.setdefault("MINIMAX_MOCK_PROVIDERS", "1")
os.environ.setdefault("DB_PATH", "./data/demo.db")
os.environ.setdefault("MEDIA_CACHE_DIR", "./data/demo_media")

# Make the repo importable when run as `python -m scripts.seed_demo`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import get_conn, reset_db  # noqa: E402
from app.ingest.chunker import chunk_notion_blocks  # noqa: E402
from app.ingest.indexer import delete_chunks_for_source, index_chunks  # noqa: E402
from app.providers import get_embedder, get_notion, get_transcriber, get_video  # noqa: E402
from app.providers.base import TranscriptResult, TranscriptSegment  # noqa: E402
from app.providers.mock_transcribe import register_fixture  # noqa: E402
from app.providers.ytdlp_video import canonicalize_url  # noqa: E402

DEMO_PAGE_ID = "mock-page-0001"
DEMO_PAGE_URL = "https://www.notion.so/demo-page-0001"

REELS = [
    {
        "url": "https://www.instagram.com/reel/DEMO_EN_1/",
        "author": "@cooking_with_anna",
        "language": "en",
        "full_original": (
            "So my grandmother taught me the dosa batter ratio is two cups of "
            "rice to one cup of urad dal. Soak them separately for four to six "
            "hours, then grind to a thick fluffy batter, ferment overnight, "
            "and add salt just before cooking."
        ),
        "segments": [
            (0.0, 5.0, "So my grandmother taught me the dosa batter ratio is two cups of rice to one cup of urad dal.",
             "So my grandmother taught me the dosa batter ratio is two cups of rice to one cup of urad dal.", "en"),
            (5.0, 11.0, "Soak them separately for four to six hours, then grind to a thick fluffy batter.",
             "Soak them separately for four to six hours, then grind to a thick fluffy batter.", "en"),
            (11.0, 16.0, "Ferment overnight, and add salt just before cooking.",
             "Ferment overnight, and add salt just before cooking.", "en"),
        ],
    },
    {
        "url": "https://www.instagram.com/reel/DEMO_HI_1/",
        "author": "@ayurveda_daily",
        "language": "hi",
        "full_original": (
            "सुबह गर्म पानी पीने से मेटाबॉलिज़्म बेहतर होता है और पाचन ठीक रहता है। "
            "एक गिलास गर्म पानी में नींबू डालकर पीने से और फायदा होता है।"
        ),
        "segments": [
            (0.0, 6.0,
             "सुबह गर्म पानी पीने से मेटाबॉलिज़्म बेहतर होता है और पाचन ठीक रहता है।",
             "Drinking warm water in the morning improves metabolism and aids digestion.", "hi"),
            (6.0, 13.0,
             "एक गिलास गर्म पानी में नींबू डालकर पीने से और फायदा होता है।",
             "Adding lemon to a glass of warm water gives even more benefit.", "hi"),
        ],
    },
    {
        "url": "https://www.instagram.com/reel/DEMO_TE_1/",
        "author": "@health_telugu",
        "language": "te",
        "full_original": (
            "రోజుకు కనీసం రెండున్నర లీటర్ల నీరు తాగాలి. "
            "వేసవిలో మూడు లీటర్లు తాగడం మంచిది. "
            "నీరు ఎక్కువ తాగితే చర్మం మెరుస్తుంది."
        ),
        "segments": [
            (0.0, 5.0,
             "రోజుకు కనీసం రెండున్నర లీటర్ల నీరు తాగాలి.",
             "You should drink at least 2.5 liters of water per day.", "te"),
            (5.0, 10.0,
             "వేసవిలో మూడు లీటర్లు తాగడం మంచిది.",
             "In summer, three liters is better.", "te"),
            (10.0, 15.0,
             "నీరు ఎక్కువ తాగితే చర్మం మెరుస్తుంది.",
             "Drinking more water makes your skin glow.", "te"),
        ],
    },
]


def _write_silent_wav(path: Path, seconds: float = 0.2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))


def seed(force_reset: bool = True) -> None:
    if force_reset:
        # Wipe the DB to start fresh.
        try:
            reset_db()
        except Exception as e:
            print(f"reset_db failed: {e}", file=sys.stderr)
    # Ensure workspace is set.
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO workspace(id, name, notion_page_id, notion_page_url, mode) "
            "VALUES (1, 'Demo workspace', ?, ?, 'token')",
            (DEMO_PAGE_ID, DEMO_PAGE_URL),
        )

    # Register mock fixtures with the transcriber BEFORE ingesting reels.
    for r in REELS:
        canonical = canonicalize_url(r["url"])
        segs = [
            TranscriptSegment(
                start=s, end=e,
                text_original=o.strip(),
                text_en=en.strip(),
                language=lang,
            )
            for (s, e, o, en, lang) in r["segments"]
        ]
        register_fixture(
            canonical,
            TranscriptResult(
                language=r["language"],
                segments=segs,
                full_text_original=r["full_original"],
                full_text_en=r["full_en"] if "full_en" in r else " ".join(s.text_en for s in segs),
                source="whisper",
            ),
        )

    # Make sure cache dirs exist.
    Path("./media_cache").mkdir(parents=True, exist_ok=True)

    # 1) Notion mock page -> persist blocks + index
    notion = get_notion()
    page = notion.get_page(DEMO_PAGE_ID, depth=0)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO notion_pages(workspace_id, notion_page_id, parent_page_id, title, url, depth, last_edited_time, last_ingested_at, status) "
            "VALUES (1, ?, NULL, ?, ?, 0, ?, datetime('now'), 'ingested')",
            (page.page_id, page.title, page.url, page.last_edited_time),
        )
        for b in page.blocks:
            conn.execute(
                "INSERT OR REPLACE INTO notion_blocks(notion_page_id, block_id, type, text, deep_link) "
                "VALUES (?, ?, ?, ?, ?)",
                (page.page_id, b.block_id, b.type, b.text, b.deep_link),
            )
        np_id = int(
            conn.execute(
                "SELECT id FROM notion_pages WHERE workspace_id = 1 AND notion_page_id = ?",
                (page.page_id,),
            ).fetchone()["id"]
        )
        blocks = [
            {
                "block_id": b.block_id,
                "type": b.type,
                "text": b.text,
                "deep_link": b.deep_link,
            }
            for b in page.blocks
        ]
        delete_chunks_for_source(conn, "notion_block", np_id)
        chunks = chunk_notion_blocks(blocks)
        index_chunks(
            conn,
            chunks,
            workspace_id=1,
            source_type="notion_block",
            source_id=np_id,
            embedder=get_embedder(),
        )
    print(f"seeded notion page: {page.title} ({len(chunks)} chunks)")

    # 2) Reels
    transcriber = get_transcriber()
    video_provider = get_video()
    embedder = get_embedder()
    for r in REELS:
        # mock video provider: write a silent wav so the transcriber has a file
        video_provider.fetch_audio(r["url"])
        # Ingest via the IG pipeline (which will call the mock transcriber)
        from app.ingest.ig_pipeline import process_reel

        with get_conn() as conn:
            process_reel(
                conn,
                workspace_id=1,
                url=r["url"],
                video_provider=video_provider,
                transcriber=transcriber,
                embedder=embedder,
            )
        # sanity: how many chunks?
        with get_conn() as conn:
            vid_id = int(
                conn.execute(
                    "SELECT id FROM videos WHERE workspace_id = 1 AND canonical_url = ?",
                    (canonicalize_url(r["url"]),),
                ).fetchone()["id"]
            )
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM chunks WHERE video_id = ?", (vid_id,)
            ).fetchone()["c"]
        print(f"seeded reel: {r['url']} ({r['language']}, {n} chunks)")

    # 3) Show counts
    with get_conn() as conn:
        c = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
        v = conn.execute("SELECT COUNT(*) AS c FROM videos").fetchone()["c"]
    print(f"\nDONE. {c} chunks across {v} videos. Run `make dev` to chat.")


if __name__ == "__main__":
    seed()
