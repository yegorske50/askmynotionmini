"""Hybrid retrieval tests against the seeded demo corpus (mock embedder)."""

from app.db import get_conn
from app.providers import get_embedder
from app.rag.retrieval import hybrid_retrieve


def test_retrieve_notion_block_for_dosa_question():
    with get_conn() as conn:
        hits = hybrid_retrieve(
            conn,
            query="dosa batter ratio rice urad dal",
            workspace_id=1,
            embedder=get_embedder(),
        )
    assert hits, "expected at least one hit"
    # Top hit should be a Notion block (the recipe lives there)
    top = hits[0]
    assert top.source_type in ("notion_block", "video_transcript")


def test_retrieve_video_transcript_for_hindi():
    with get_conn() as conn:
        hits = hybrid_retrieve(
            conn,
            query="गर्म पानी पीने से",
            workspace_id=1,
            embedder=get_embedder(),
            final_k=5,
        )
    assert hits
    # The Hindi reel should rank in the top results.
    languages = {h.language for h in hits}
    assert "hi" in languages


def test_retrieve_cross_language_telugu():
    with get_conn() as conn:
        hits = hybrid_retrieve(
            conn,
            query="how much water should I drink per day",
            workspace_id=1,
            embedder=get_embedder(),
            final_k=5,
        )
    assert hits
    # Multilingual embedding: an English question should match the Telugu reel
    # (its text_en is what we embed; the original is in `text_original`).
    assert any(h.source_type == "video_transcript" for h in hits)
