"""Chunker unit tests."""

from app.ingest.chunker import chunk_notion_blocks, chunk_transcript_segments


def test_chunk_notion_blocks_basic():
    blocks = [
        {"block_id": "a", "type": "paragraph", "text": "First paragraph.", "deep_link": "#a"},
        {"block_id": "b", "type": "heading_1", "text": "Heading", "deep_link": "#b"},
    ]
    chunks = chunk_notion_blocks(blocks)
    assert len(chunks) == 2
    assert "First paragraph" in chunks[0].text_original
    assert chunks[0].meta["block_ids"] == ["a"]
    assert chunks[1].meta["block_ids"] == ["b"]


def test_chunk_notion_blocks_merge_same_type():
    blocks = [
        {"block_id": "a", "type": "paragraph", "text": "a" * 50, "deep_link": "#a"},
        {"block_id": "b", "type": "paragraph", "text": "b" * 50, "deep_link": "#b"},
        {"block_id": "c", "type": "heading_1", "text": "C", "deep_link": "#c"},
    ]
    chunks = chunk_notion_blocks(blocks, max_chars=300)
    # a and b should merge; c is a heading_1 so stays separate
    assert len(chunks) == 2
    merged = [c for c in chunks if len(c.text_original) > 50][0]
    assert "a" * 50 in merged.text_original and "b" * 50 in merged.text_original


def test_chunk_transcript_silence_split():
    segs = [
        {"start": 0.0, "end": 3.0, "text_original": "Hello there", "text_en": "Hello there", "language": "en"},
        {"start": 3.0, "end": 6.0, "text_original": "how are you", "text_en": "how are you", "language": "en"},
        # 4s silence boundary
        {"start": 10.0, "end": 13.0, "text_original": "I am fine", "text_en": "I am fine", "language": "en"},
    ]
    chunks = chunk_transcript_segments(segs, min_silence_gap=2.0)
    assert len(chunks) == 2
    assert chunks[0].start_sec == 0.0 and chunks[0].end_sec == 6.0
    assert chunks[1].start_sec == 10.0 and chunks[1].end_sec == 13.0
