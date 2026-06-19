"""Mock transcriber — deterministic canned transcripts keyed by URL.

Used by tests + the seeded demo (scripts/seed_demo.py registers fixtures).
"""

from __future__ import annotations

from pathlib import Path

from app.providers.base import TranscriptionProvider, TranscriptResult

_FIXTURES: dict[str, TranscriptResult] = {}


def register_fixture(canonical_url: str, result: TranscriptResult) -> None:
    _FIXTURES[canonical_url] = result


class MockTranscriber(TranscriptionProvider):
    name = "mock"

    def transcribe(self, audio_path: str, *, language: str | None = None) -> TranscriptResult:
        # For tests we key on the audio_path basename. The mock video provider
        # writes a file named after the canonical URL: it collapses every
        # run of non-alphanumeric chars to a single `_`. We just need a
        # substring match — the canonical URL is encoded in the stem.
        p = Path(audio_path)
        stem = p.stem  # filename without extension
        for url, result in _FIXTURES.items():
            canon_no_slash = url.rstrip("/")
            # Extract the path portion (after the host) and check the slug
            slug = canon_no_slash.split("/")[-1]  # e.g. "DEMO_EN_1"
            if slug and slug in stem:
                return result
        return TranscriptResult(
            language=language or "unknown",
            segments=[],
            full_text_original="",
            full_text_en="",
            source="whisper",
        )
