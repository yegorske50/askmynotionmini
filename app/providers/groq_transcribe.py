"""Groq Whisper transcription provider.

We translate to English via the same call (Whisper `translate` task) so we get
both original and English segment lists in one round-trip.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.providers.base import TranscriptionProvider, TranscriptResult, TranscriptSegment


class GroqTranscriber(TranscriptionProvider):
    name = "groq"

    def __init__(self, api_key: str, base_url: str = "https://api.groq.com/openai/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=180.0)

    def transcribe(self, audio_path: str, *, language: str | None = None) -> TranscriptResult:
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size == 0:
            return TranscriptResult(
                language=language or "unknown",
                segments=[],
                full_text_original="",
                full_text_en="",
                source="whisper",
            )

        headers = {"Authorization": f"Bearer {self.api_key}"}
        common = {
            "model": "whisper-large-v3",
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            common["language"] = language

        def call(task: str) -> dict:
            files = {"file": (path.name, open(path, "rb"), "audio/wav")}
            data = {**common, "task": task}
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    r = self._client.post(
                        f"{self.base_url}/audio/transcriptions",
                        headers=headers,
                        data=data,
                        files=files,
                    )
                    files["file"][1].seek(0)  # rewind for retry
                    if r.status_code == 429 or r.status_code >= 500:
                        time.sleep(2 ** attempt)
                        continue
                    r.raise_for_status()
                    return r.json()
                except Exception as e:
                    last_err = e
                    time.sleep(2 ** attempt)
            raise RuntimeError(f"Groq transcription failed: {last_err}")

        orig_data = call("transcribe")
        en_data = call("translate") if (orig_data.get("language") or "").lower() not in ("en", "english") else orig_data

        lang = (orig_data.get("language") or language or "unknown")
        segs_orig = orig_data.get("segments") or []
        segs_en = en_data.get("segments") or []

        # Zip by index for translation; Whisper segments are aligned across tasks
        # when run on the same audio. We attach English text to each segment.
        segments: list[TranscriptSegment] = []
        for i, s in enumerate(segs_orig):
            en_text = ""
            if i < len(segs_en):
                en_text = (segs_en[i].get("text") or "").strip()
            segments.append(
                TranscriptSegment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text_original=(s.get("text") or "").strip(),
                    text_en=en_text,
                    language=lang,
                )
            )

        full_orig = (orig_data.get("text") or "").strip()
        full_en = (en_data.get("text") or "").strip() if en_data is not orig_data else full_orig

        return TranscriptResult(
            language=lang,
            segments=segments,
            full_text_original=full_orig,
            full_text_en=full_en or full_orig,
            source="whisper",
        )
