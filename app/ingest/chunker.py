"""Chunking for Notion blocks and video transcripts.

Notion blocks: 1 chunk per block (or merged if very small and adjacent).
Video transcripts: split on >=2s silence boundaries; each chunk keeps
[start, end] seconds for inline timestamping in answers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text_original: str
    text_en: str | None
    language: str | None
    start_sec: float | None = None
    end_sec: float | None = None
    meta: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.meta is None:
            self.meta = {}


def chunk_notion_blocks(blocks: list[dict], max_chars: int = 1800) -> list[Chunk]:
    """Each block becomes one chunk; merge tiny consecutive blocks of same kind
    when the combined size is still under max_chars.

    blocks: list of dicts with keys: block_id, type, text, deep_link
    """
    chunks: list[Chunk] = []
    buf: list[dict] = []
    buf_len = 0

    def flush():
        nonlocal buf, buf_len
        if not buf:
            return
        text = "\n\n".join(b["text"] for b in buf).strip()
        if not text:
            buf, buf_len = [], 0
            return
        chunks.append(
            Chunk(
                text_original=text,
                text_en=text,  # Notion is whatever the user wrote; no translation
                language=None,
                meta={
                    "block_ids": [b["block_id"] for b in buf],
                    "deep_link": buf[-1]["deep_link"],
                    "types": [b["type"] for b in buf],
                },
            )
        )
        buf, buf_len = [], 0

    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        if buf and (buf[-1]["type"] == b["type"]) and (buf_len + len(text) <= max_chars):
            buf.append(b)
            buf_len += len(text) + 2
        else:
            flush()
            buf = [b]
            buf_len = len(text)
    flush()
    return chunks


def chunk_transcript_segments(
    segments: list[dict],
    *,
    target_chars: int = 1200,
    min_silence_gap: float = 2.0,
) -> list[Chunk]:
    """Group consecutive segments until target_chars, splitting on >=2s gaps."""
    if not segments:
        return []
    chunks: list[Chunk] = []
    cur: list[dict] = []
    cur_len = 0
    cur_lang = segments[0].get("language") or "unknown"

    def flush():
        nonlocal cur, cur_len
        if not cur:
            return
        text_o = " ".join(s.get("text_original", "").strip() for s in cur).strip()
        text_e = " ".join(s.get("text_en", "").strip() for s in cur).strip() or text_o
        if text_o:
            chunks.append(
                Chunk(
                    text_original=text_o,
                    text_en=text_e,
                    language=cur_lang,
                    start_sec=cur[0].get("start", 0.0),
                    end_sec=cur[-1].get("end", 0.0),
                    meta={"seg_count": len(cur)},
                )
            )
        cur, cur_len = [], 0

    for s in segments:
        s_text = (s.get("text_original") or "").strip()
        if not s_text:
            continue
        gap = 0.0
        if cur:
            gap = float(s.get("start", 0.0)) - float(cur[-1].get("end", 0.0))
        if cur and (cur_len + len(s_text) > target_chars or gap >= min_silence_gap):
            flush()
        cur.append(s)
        cur_len += len(s_text) + 1
    flush()
    return chunks
