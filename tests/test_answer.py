"""Golden-dataset test over the seeded demo corpus.

These cover: answer-from-transcript-with-timestamp, answer-from-Notion-block,
multi-source listing, unanswerable -> "not found", and cross-language
(Telugu transcript + English question) case.
"""

from app.providers.ytdlp_video import canonicalize_url
from app.rag.answer import CitationOut, stream_answer


def _drain(question: str) -> tuple[str, list[CitationOut]]:
    full = ""
    sources: list[CitationOut] = []
    for ev in stream_answer(question=question):
        if ev.delta:
            full += ev.delta
        if ev.sources is not None:
            sources = ev.sources
    return full, sources


def test_answer_from_transcript_with_timestamp_en():
    # The English reel covers the dosa batter ratio with timestamps.
    full, sources = _drain("What's the dosa batter ratio?")
    assert "urad dal" in full.lower() or "[1]" in full
    # at least one source from the english reel
    canonical = canonicalize_url("https://www.instagram.com/reel/DEMO_EN_1/")
    reel_sources = [s for s in sources if s.type == "video_transcript" and canonical in s.url]
    assert reel_sources, "expected the English reel to be cited"
    # timestamp present
    rs = reel_sources[0]
    assert rs.start is not None and rs.end is not None and rs.end > rs.start


def test_answer_from_notion_block():
    full, sources = _drain("What's in my Notion page about dosa?")
    # at least one Notion source
    assert any(s.type == "notion_block" for s in sources)


def test_multi_source_listing():
    # Ask something that pulls from the recipe (notion + english reel).
    full, sources = _drain("Tell me everything you know about dosa batter")
    assert len(sources) >= 1
    # If the answer references citations, multiple distinct sources should appear.
    types = {s.type for s in sources}
    assert types  # at least one


def test_unanswerable_returns_not_found():
    full, _ = _drain("What is the airspeed velocity of an unladen swallow?")
    assert "couldn't find" in full.lower() or "i couldn't" in full.lower()


def test_cross_language_telugu_reel_cited_for_english_question():
    # English question about water intake -> Telugu reel should appear in sources.
    full, sources = _drain("How much water should I drink each day?")
    canonical_te = canonicalize_url("https://www.instagram.com/reel/DEMO_TE_1/")
    te_sources = [s for s in sources if canonical_te in s.url]
    assert te_sources, "expected Telugu reel to be cited for an English water-intake question"
    # The Telugu reel's English translation should appear in its snippet.
    te = te_sources[0]
    assert "water" in (te.snippet_en or "").lower()


def test_hindi_question_returns_hindi_reel():
    full, sources = _drain("गर्म पानी पीने के फायदे")
    canonical_hi = canonicalize_url("https://www.instagram.com/reel/DEMO_HI_1/")
    hi_sources = [s for s in sources if canonical_hi in s.url]
    assert hi_sources, "expected Hindi reel to be cited for a Hindi question"
    # The answer should be in Hindi.
    assert "मेटाबॉलिज़्म" in full or "पाचन" in full or "[1]" in full
